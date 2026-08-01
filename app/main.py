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
    DETAIL_SELECT,
    INPUT_MESSAGES_EXPR,
    LIST_SELECT,
    MODEL_EXPR,
    OUTPUT_TEXT_EXPR,
    SERVICE_FILTER,
    STATUS_EXPR,
    TAGS_EXPR,
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

    where: list[str] = [SERVICE_FILTER]
    params: dict[str, Any] = {}

    if since:
        where.append("Timestamp >= {since:DateTime64(3)}")
        params["since"] = _parse_query_datetime(since, "since")
    else:
        where.append("Timestamp >= now() - INTERVAL 24 HOUR")

    if until:
        where.append("Timestamp <= {until:DateTime64(3)}")
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

    where_sql = " AND ".join(where)
    pagination_sql = "" if fetch_all else f"LIMIT {limit} OFFSET {offset}"

    sql = f"""
        SELECT {LIST_SELECT}
        FROM otel_traces
        WHERE {where_sql}
        ORDER BY Timestamp DESC
        {pagination_sql}
    """

    client = get_client()
    result = client.query(sql, parameters=params)
    rows = [dict(zip(result.column_names, row)) for row in result.result_rows]
    for r in rows:
        r["timestamp"] = _iso_timestamp(r.get("timestamp"))
    return {"rows": rows, "limit": limit, "offset": offset}


@app.get("/api/calls/{request_id}")
async def get_call(request_id: str) -> dict[str, Any]:
    client = get_client()
    result = client.query(
        f"""
        SELECT {DETAIL_SELECT}
        FROM otel_traces
        WHERE {SERVICE_FILTER}
          AND SpanId = {{rid:String}}
        ORDER BY Timestamp DESC
        LIMIT 1
        """,
        parameters={"rid": request_id},
    )
    if not result.result_rows:
        raise HTTPException(status_code=404, detail="not found")
    row = dict(zip(result.column_names, result.result_rows[0]))
    row["timestamp"] = _iso_timestamp(row.get("timestamp"))
    return row


@app.get("/api/tags")
async def list_tags() -> dict[str, Any]:
    client = get_client()
    result = client.query(
        f"""
        SELECT DISTINCT t
        FROM (
            SELECT {TAGS_EXPR} AS tags
            FROM otel_traces
            WHERE {SERVICE_FILTER}
              AND Timestamp >= now() - INTERVAL 7 DAY
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
        SELECT {MODEL_EXPR} AS model, count() AS n
        FROM otel_traces
        WHERE {SERVICE_FILTER}
          AND Timestamp >= now() - INTERVAL 7 DAY
          AND {MODEL_EXPR} != ''
        GROUP BY model
        ORDER BY n DESC
        """
    )
    return {"models": [r[0] for r in result.result_rows]}


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
