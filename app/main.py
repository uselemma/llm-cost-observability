"""FastAPI dashboard over aig.otel_traces.

Auth is Cloudflare Access at the edge — this app does not validate sessions.
"""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.cel_filter import compile_cel_filter, list_queryable_cel_fields
from app.ch import get_client
from app.queries import (
    ATTEMPTS_SELECT,
    DETAIL_SELECT,
    INPUT_MESSAGES_EXPR,
    LIST_SELECT,
    MODEL_EXPR,
    OUTPUT_TEXT_EXPR,
    RAW_CALL_ID_EXPR,
    SERVICE_FILTER,
    STATUS_EXPR,
    TAGS_EXPR,
    VERCEL_SOURCE_EXPR,
    logical_calls_cte,
)

DASHBOARD_DIST = Path(os.environ.get("DASHBOARD_DIST", "dashboard/dist"))

app = FastAPI(title="LLM cost observability", docs_url=None, redoc_url=None)


def _parse_query_datetime(value: str, field: str) -> str:
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"invalid {field} datetime, expected ISO format",
        )
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _iso_timestamp(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc).isoformat()
    return value


@app.get("/api/me")
async def me() -> dict[str, Any]:
    return {"authenticated": True, "env": None}


@app.get("/api/calls")
async def list_calls(
    since: str | None = None,
    until: str | None = None,
    model: str | None = None,
    status: str | None = None,
    tag: list[str] = Query(default_factory=list),
    cel: str | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    fetch_all = limit == 0
    if not fetch_all:
        limit = max(1, limit)
        offset = max(0, offset)

    where: list[str] = []
    source_where: list[str] = []
    params: dict[str, Any] = {}

    if since:
        source_where.append("Timestamp >= subtractMinutes({since:DateTime64(3)}, 2)")
        where.append("timestamp >= {since:DateTime64(3)}")
        params["since"] = _parse_query_datetime(since, "since")
    else:
        source_where.append("Timestamp >= now() - INTERVAL 24 HOUR - INTERVAL 2 MINUTE")
        where.append("timestamp >= now() - INTERVAL 24 HOUR")

    if until:
        source_where.append("Timestamp <= addMinutes({until:DateTime64(3)}, 2)")
        where.append("timestamp <= {until:DateTime64(3)}")
        params["until"] = _parse_query_datetime(until, "until")
    if model:
        where.append(f"{MODEL_EXPR} = {{model:String}}")
        params["model"] = model
    if status:
        where.append(f"({STATUS_EXPR}) = {{status:String}}")
        params["status"] = status
    if tag:
        # Group selected tags by key (prefix before first ':').
        # OR within a key, AND across keys.
        groups: dict[str, list[str]] = defaultdict(list)
        for t in tag:
            key, _, _ = t.partition(":")
            groups[key].append(t)
        for i, vals in enumerate(groups.values()):
            ors: list[str] = []
            for j, v in enumerate(vals):
                pname = f"tag_{i}_{j}"
                ors.append(f"has(({TAGS_EXPR}), {{{pname}:String}})")
                params[pname] = v
            where.append("(" + " OR ".join(ors) + ")")
    if cel and cel.strip():
        try:
            cel_sql, cel_params = compile_cel_filter(cel.strip())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"invalid cel filter: {exc}")
        where.append(f"({cel_sql})")
        params.update(cel_params)
    if q:
        where.append(
            f"(positionCaseInsensitive({OUTPUT_TEXT_EXPR}, {{q:String}}) > 0 "
            f"OR positionCaseInsensitive({INPUT_MESSAGES_EXPR}, {{q:String}}) > 0)"
        )
        params["q"] = q

    where_sql = " AND ".join(where) if where else "1"
    pagination_sql = "" if fetch_all else f"LIMIT {limit} OFFSET {offset}"

    sql = f"""
        {logical_calls_cte(" AND ".join(source_where))}
        SELECT {LIST_SELECT}
        FROM logical_calls
        WHERE {where_sql}
        ORDER BY timestamp DESC
        {pagination_sql}
    """

    client = get_client()
    result = client.query(sql, parameters=params)
    rows = [dict(zip(result.column_names, row)) for row in result.result_rows]
    for r in rows:
        r["timestamp"] = _iso_timestamp(r.get("timestamp"))
    return {"rows": rows, "limit": limit, "offset": offset}


@app.get("/api/calls/{request_id}")
async def get_call(request_id: str, timestamp: str | None = None) -> dict[str, Any]:
    client = get_client()
    params: dict[str, Any] = {"rid": request_id}
    source_selector = f"({RAW_CALL_ID_EXPR} = {{rid:String}} OR SpanId = {{rid:String}})"
    if timestamp:
        params["selected_timestamp"] = _parse_query_datetime(timestamp, "timestamp")
        source_selector = (
            "Timestamp >= subtractMinutes({selected_timestamp:DateTime64(3)}, 2) "
            "AND Timestamp <= addMinutes({selected_timestamp:DateTime64(3)}, 2) "
            f"AND {source_selector}"
        )
    result = client.query(
        f"""
        {logical_calls_cte(source_selector)}
        SELECT {DETAIL_SELECT}
        FROM logical_calls
        WHERE request_id = {{rid:String}}
        LIMIT 1
        """,
        parameters=params,
    )
    if not result.result_rows:
        raise HTTPException(status_code=404, detail="not found")
    row = dict(zip(result.column_names, result.result_rows[0]))
    row["timestamp"] = _iso_timestamp(row.get("timestamp"))
    trace_ids = row.pop("vercel_trace_ids", [])
    row["attempts"] = []
    if trace_ids:
        attempts_result = client.query(
            f"""
            SELECT {ATTEMPTS_SELECT}
            FROM otel_traces
            WHERE {SERVICE_FILTER}
              AND {VERCEL_SOURCE_EXPR}
              AND TraceId IN {{trace_ids:Array(String)}}
              AND NOT empty(ParentSpanId)
            ORDER BY Timestamp, SpanId
            """,
            parameters={"trace_ids": trace_ids},
        )
        row["attempts"] = [
            dict(zip(attempts_result.column_names, attempt))
            for attempt in attempts_result.result_rows
        ]
    return row


@app.get("/api/tags")
async def list_tags() -> dict[str, Any]:
    client = get_client()
    result = client.query(
        f"""
        {logical_calls_cte("Timestamp >= now() - INTERVAL 7 DAY - INTERVAL 2 MINUTE")}
        SELECT DISTINCT t
        FROM (
            SELECT {TAGS_EXPR} AS tags
            FROM logical_calls
            WHERE timestamp >= now() - INTERVAL 7 DAY
        )
        ARRAY JOIN tags AS t
        ORDER BY t
        """
    )
    return {"tags": [r[0] for r in result.result_rows]}


@app.get("/api/models")
async def list_models() -> dict[str, Any]:
    client = get_client()
    result = client.query(
        f"""
        {logical_calls_cte("Timestamp >= now() - INTERVAL 7 DAY - INTERVAL 2 MINUTE")}
        SELECT {MODEL_EXPR} AS model, count() AS n
        FROM logical_calls
        WHERE timestamp >= now() - INTERVAL 7 DAY
          AND {MODEL_EXPR} != ''
        GROUP BY model
        ORDER BY n DESC
        """
    )
    return {"models": [r[0] for r in result.result_rows]}


@app.get("/api/reconciliation")
async def reconciliation_metrics(
    since: str | None = None,
    until: str | None = None,
) -> dict[str, Any]:
    """Canary/SLO metrics for dual-gateway calls with a shared call_id."""
    params: dict[str, Any] = {}
    source_where = ["Timestamp >= now() - INTERVAL 24 HOUR - INTERVAL 2 MINUTE"]
    projected_where = ["timestamp >= now() - INTERVAL 24 HOUR"]
    if since:
        params["since"] = _parse_query_datetime(since, "since")
        source_where = ["Timestamp >= subtractMinutes({since:DateTime64(3)}, 2)"]
        projected_where = ["timestamp >= {since:DateTime64(3)}"]
    if until:
        params["until"] = _parse_query_datetime(until, "until")
        source_where.append("Timestamp <= addMinutes({until:DateTime64(3)}, 2)")
        projected_where.append("timestamp <= {until:DateTime64(3)}")

    client = get_client()
    result = client.query(
        f"""
        {logical_calls_cte(" AND ".join(source_where))}
        SELECT
            count() AS identified_calls,
            countIf(reconciliation_status = 'reconciled') AS reconciled_calls,
            countIf(reconciliation_status = 'cache_hit') AS exact_cache_hits,
            countIf(reconciliation_status = 'unreconciled') AS unreconciled_calls,
            countIf(reconciliation_overdue = 1) AS overdue_calls,
            countIf(
                timestamp <= now64(3) - INTERVAL 2 MINUTE
            ) AS matured_calls,
            countIf(
                timestamp <= now64(3) - INTERVAL 2 MINUTE
                AND is_complete = 1
            ) AS matured_complete_calls,
            if(
                matured_calls = 0,
                1.,
                matured_complete_calls / matured_calls
            ) AS completeness_after_2m,
            quantileExactIf(0.99)(
                reconciliation_ms,
                reconciliation_status = 'reconciled'
            ) AS p99_reconciliation_ms,
            toUInt8(completeness_after_2m >= 0.99) AS meets_99pct_2m_slo
        FROM logical_calls
        WHERE call_id != ''
          AND {" AND ".join(projected_where)}
        """,
        parameters=params,
    )
    row = dict(zip(result.column_names, result.result_rows[0]))
    return row


@app.get("/api/cel-fields")
async def list_cel_fields() -> dict[str, Any]:
    return {"fields": list_queryable_cel_fields()}


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# --- Static SPA --------------------------------------------------------------

if DASHBOARD_DIST.is_dir():
    assets_dir = DASHBOARD_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/")
    async def spa_index() -> FileResponse:
        return FileResponse(DASHBOARD_DIST / "index.html")

    @app.get("/{path:path}")
    async def spa_fallback(path: str) -> FileResponse:
        candidate = DASHBOARD_DIST / path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(DASHBOARD_DIST / "index.html")
