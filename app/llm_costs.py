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
from app.cost_export import DEFAULT_LOOKBACK_DAYS, CostExportError, CostReport, resolve_range
from app.queries import (
    FEATURE_EXPR,
    MODEL_EXPR,
    PROVIDER_EXPR,
    SPEND_EXPR,
    STATUS_EXPR,
    logical_calls_cte,
)


@dataclass(frozen=True)
class LlmCostRow:
    date: str
    model: str
    provider: str
    feature: str
    spend_usd: float
    calls: int


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
    rollup = f"""
    SELECT
        toString(toDate(timestamp)) AS day,
        if({MODEL_EXPR} = '', 'unknown', {MODEL_EXPR}) AS model_out,
        if({PROVIDER_EXPR} = '', 'unknown', {PROVIDER_EXPR}) AS provider_out,
        if({FEATURE_EXPR} = '', 'untagged', {FEATURE_EXPR}) AS feature_out,
        sum({SPEND_EXPR}) AS total_spend_usd,
        countIf({STATUS_EXPR} = 'success') AS success_calls
    FROM logical_calls
    """
    query = logical_calls_cte(source_where) + rollup + """
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
