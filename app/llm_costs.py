"""Daily LLM spend over the logical-call projection (app.queries).

Queried one day per ClickHouse round trip; a single 14-day aggregation
exhausted ClickHouse Cloud's temporary storage in production. See
get_daily_costs.

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
# One day per query. See get_daily_costs for the production failure that
# forced chunking; raise it only if ClickHouse has headroom to spare.
DEFAULT_CHUNK_DAYS = 1


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


def _build_query(start: date, end: date) -> str:
    """Rollup query for the half-open day range [start, end)."""
    # Widen the raw-span scan +/-2 minutes (matches app.main's pattern) so
    # reconciliation pairs straddling the boundary stay whole, then pin the
    # rollup to each logical call's own day. Reconciliation joins on the
    # gateway call id rather than on time proximity, so the margin only has
    # to be wide enough that both spans of one request land in the same scan
    # -- they are emitted within seconds of each other.
    # start/end are validated date objects -- safe to inline as ISO literals.
    source_where = (
        f"Timestamp >= toDateTime('{start.isoformat()} 00:00:00') - INTERVAL 2 MINUTE"
        f" AND Timestamp < toDateTime('{end.isoformat()} 00:00:00') + INTERVAL 2 MINUTE"
    )
    return f"""
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


def chunk_days(env: dict[str, str] | None = None) -> int:
    """Days of data per ClickHouse query. See get_daily_costs for why."""
    e = env if env is not None else os.environ
    raw = (e.get("LLM_COST_CHUNK_DAYS") or "").strip()
    if not raw:
        return DEFAULT_CHUNK_DAYS
    try:
        value = int(raw)
    except ValueError as exc:
        raise LlmCostError(
            f"invalid LLM_COST_CHUNK_DAYS {raw!r}; expected an integer"
        ) from exc
    if value < 1:
        raise LlmCostError("LLM_COST_CHUNK_DAYS must be >= 1")
    return value


def _windows(start: date, end: date, size: int) -> list[tuple[date, date]]:
    """Split [start, end) into consecutive half-open ranges of `size` days."""
    windows: list[tuple[date, date]] = []
    cursor = start
    while cursor < end:
        stop = min(cursor + timedelta(days=size), end)
        windows.append((cursor, stop))
        cursor = stop
    return windows


def get_daily_costs(
    since: str | None = None,
    until: str | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return daily spend and successful-call counts for the window.

    Queried one day at a time rather than as a single range. Aggregating the
    logical-call CTE over a full 14-day window exhausted ClickHouse Cloud's
    temporary storage in production (code 243 NOT_ENOUGH_SPACE, ~45 GiB of
    ephemeral hold in AggregatingTransform), which failed the whole vendor and
    dropped model spend from the dashboard entirely. Chunking makes peak
    memory a function of one day's traffic instead of the lookback length, so
    widening the window no longer risks the same failure.

    Rows are grouped by day, so per-chunk results concatenate without any
    cross-chunk aggregation. Chunk boundaries fall at midnight and each chunk
    scans two minutes past its own edges, so a reconciliation pair split
    across midnight is still resolved whole.

    A chunk that fails is reported in the returned "errors" list rather than
    aborting the run, because one heavy day used to destroy the whole window:
    a single day exceeding ClickHouse Cloud's 7.2 GiB limit emptied all 14,
    and chunking is already at its one-day floor with nowhere smaller to
    retreat to. Only a connection failure, or every chunk failing, raises.
    """
    start, end = resolve_range(since, until, lookback_days)
    size = chunk_days(env)

    # One client for every chunk -- reconnecting per day would multiply
    # handshake cost by the lookback length. Connecting is inside the try so
    # an unreachable or misconfigured ClickHouse still surfaces as
    # LlmCostError rather than leaking a driver exception to the caller.
    try:
        client = get_client()
    except Exception as exc:  # noqa: BLE001 -- one error type for the CLI
        raise LlmCostError(f"clickhouse connection failed: {exc}") from exc

    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    windows = _windows(start, end, size)
    for window_start, window_end in windows:
        try:
            result = client.query(_build_query(window_start, window_end))
        except Exception as exc:  # noqa: BLE001 -- one error type for the CLI
            # Name the failing chunk; "the query failed" over a 14d window
            # gave no clue which day was too heavy.
            errors.append(
                f"{window_start.isoformat()}..{window_end.isoformat()}: {exc}"
            )
            continue

        rows.extend(
            {
                "date": str(day),
                "model": str(model),
                "provider": str(provider),
                "feature": str(feature),
                "spend_usd": float(spend_usd),
                "calls": int(calls),
            }
            for day, model, provider, feature, spend_usd, calls in result.result_rows
        )

    if errors and len(errors) == len(windows):
        raise LlmCostError("; ".join(errors))

    return {
        "rows": rows,
        "since": start.isoformat(),
        "until": (end - timedelta(days=1)).isoformat(),
        "errors": errors,
    }
