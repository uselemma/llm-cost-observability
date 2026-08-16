"""Daily LLM spend over the logical-call projection (app.queries).

One row per (day, model, provider, feature), aggregated from logical calls so
dual-gateway (Cloudflare + Vercel) roots are never double-counted. Spend
follows the projection's own cost semantics: Vercel billed cost for
reconciled calls, the Cloudflare estimate for legacy calls, zero for exact
cache hits and calls still awaiting reconciliation.
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any

from app.ch import get_client
from app.queries import logical_calls_cte

DEFAULT_LOOKBACK_DAYS = 14


class LlmCostError(Exception):
    """Raised when the ClickHouse spend query cannot be built or run."""


def _parse_day(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError as exc:
        raise LlmCostError(f"invalid {field} date, expected YYYY-MM-DD") from exc


def resolve_range(
    since: str | None, until: str | None, lookback_days: int
) -> tuple[date, date]:
    """Return (inclusive start day, exclusive end day)."""
    default_end = date.today() + timedelta(days=1)
    start = (
        _parse_day(since, "since")
        if since
        else default_end - timedelta(days=max(1, lookback_days))
    )
    end = _parse_day(until, "until") + timedelta(days=1) if until else default_end
    if end <= start:
        raise LlmCostError("until must be on or after since")
    return start, end


def get_daily_costs(
    since: str | None = None,
    until: str | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, Any]:
    """Return daily spend and successful-call counts for the window."""
    start, end = resolve_range(since, until, lookback_days)

    # Widen the raw-span scan +/-2 minutes (matches app.main's pattern) so
    # reconciliation pairs straddling the boundary stay whole, then pin the
    # rollup to each logical call's own day.
    # start/end are validated date objects -- safe to inline as ISO literals.
    source_where = (
        f"Timestamp >= toDateTime('{start.isoformat()} 00:00:00') - INTERVAL 2 MINUTE"
        f" AND Timestamp < toDateTime('{end.isoformat()} 00:00:00') + INTERVAL 2 MINUTE"
    )
    query = f"""
    {logical_calls_cte(source_where)}
    SELECT
        toString(toDate(timestamp)) AS day,
        if(model = '', 'unknown', model) AS model_out,
        if(provider = '', 'unknown', provider) AS provider_out,
        if(SpanAttributes['feature'] = '', 'untagged',
           SpanAttributes['feature']) AS feature_out,
        sum(spend_usd) AS total_spend_usd,
        countIf(status = 'success') AS success_calls
    FROM logical_calls
    WHERE toDate(timestamp) >= toDate('{start.isoformat()}')
      AND toDate(timestamp) < toDate('{end.isoformat()}')
    GROUP BY day, model_out, provider_out, feature_out
    ORDER BY day, model_out, provider_out, feature_out
    """

    try:
        result = get_client().query(query)
    except Exception as exc:  # noqa: BLE001 -- one error type for the CLI
        raise LlmCostError(str(exc)) from exc

    rows = [
        {
            "date": str(day),
            "model": str(model),
            "provider": str(provider),
            "feature": str(feature),
            "spend_usd": float(spend_usd),
            "calls": int(calls),
        }
        for day, model, provider, feature, spend_usd, calls in result.result_rows
    ]

    return {
        "rows": rows,
        "since": start.isoformat(),
        "until": (end - timedelta(days=1)).isoformat(),
    }
