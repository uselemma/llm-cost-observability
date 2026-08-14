"""Daily LLM spend over the ENG-655 logical-call projection.

Data layer for the llm.cost.estimated / llm.calls Dash0 export: one row per
(day, model, provider, feature) aggregated from logical calls, so dual-gateway
(Cloudflare + Vercel) roots are never double-counted. Spend follows the
projection's cost semantics: Vercel billed cost for reconciled calls, the
Cloudflare estimate for legacy calls, zero for cache hits and calls still
awaiting reconciliation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.ch import get_client
from app.cost_export import CostExportError, CostReport, resolve_range
from app.queries import logical_calls_cte

DEFAULT_LOOKBACK_DAYS = 14


@dataclass(frozen=True)
class LlmCostRow:
    date: str
    model: str
    provider: str
    feature: str
    spend_usd: float
    calls: int

    def gauge_attributes(self) -> dict[str, str]:
        return {
            "llm.cost.date": self.date,
            "gen_ai.request.model": self.model,
            "gen_ai.provider.name": self.provider,
            "feature": self.feature,
        }


class LlmCostError(CostExportError):
    """Raised when the ClickHouse spend query cannot be built or run."""


def get_daily_costs(
    since: str | None = None,
    until: str | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> CostReport[LlmCostRow]:
    """Return daily spend and successful-call counts for the window."""
    window = resolve_range(since, until, lookback_days)
    start_dt = datetime.combine(window.start, datetime.min.time())
    end_dt = datetime.combine(window.end, datetime.min.time())

    # Widen the raw-span scan ±2 minutes (like app.main) so reconciliation
    # pairs straddling the boundary stay whole, then pin the rollup to the
    # logical call's own day.
    source_where = (
        "Timestamp >= subtractMinutes({start:DateTime}, 2)"
        " AND Timestamp < addMinutes({end:DateTime}, 2)"
    )
    query = logical_calls_cte(source_where) + """
    SELECT
        toString(toDate(timestamp)) AS day,
        if(model = '', 'unknown', model) AS model_out,
        if(provider = '', 'unknown', provider) AS provider_out,
        if(SpanAttributes['feature'] = '', 'untagged',
           SpanAttributes['feature']) AS feature_out,
        sum(spend_usd) AS total_spend_usd,
        countIf(status = 'success') AS success_calls
    FROM logical_calls
    WHERE toDate(timestamp) >= toDate({start:DateTime})
      AND toDate(timestamp) < toDate({end:DateTime})
    GROUP BY day, model_out, provider_out, feature_out
    ORDER BY day, model_out, provider_out, feature_out
    """

    try:
        result = get_client().query(
            query, parameters={"start": start_dt, "end": end_dt}
        )
    except Exception as exc:  # noqa: BLE001 — one error type for the CLI
        raise LlmCostError(str(exc)) from exc

    rows = [
        LlmCostRow(
            date=str(day),
            model=str(model),
            provider=str(provider),
            feature=str(feature),
            spend_usd=float(spend_usd),
            calls=int(calls),
        )
        for day, model, provider, feature, spend_usd, calls in result.result_rows
    ]
    return CostReport(rows=rows, window=window)
