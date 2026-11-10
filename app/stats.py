"""Aggregate usage endpoints for the dashboard charts.

Every query is time-bounded (see filters.time_where) and only touches specific
SpanAttributes keys — never the prompt/completion bodies, which make scans slow.
"""
from __future__ import annotations

import json
import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.ch import get_client
from app import pricing
from app.filters import NONE_LABEL, StatsFilters, stats_filters
from app.span_queries import DIMENSION_EXPR, STATS_AGGREGATES

router = APIRouter(prefix="/api/stats")

BUCKET_INTERVALS = {
    "1min": "1 MINUTE",
    "5min": "5 MINUTE",
    "15min": "15 MINUTE",
    "30min": "30 MINUTE",
    "hour": "1 HOUR",
    "6hour": "6 HOUR",
    "day": "1 DAY",
}
Bucket = Literal["1min", "5min", "15min", "30min", "hour", "6hour", "day"]

Dimension = Literal[
    "model", "provider", "feature", "feature_parent", "prompt", "project_id", "variant"
]
OTHER_LABEL = "Other"
MAX_GROUPS = 500


def _label(value: Any) -> str:
    return value if value else NONE_LABEL


def _num(value: Any) -> float:
    # quantile() over zero rows returns nan.
    return 0.0 if value is None or value != value else float(value)


def _metrics(row: dict[str, Any]) -> dict[str, Any]:
    calls = int(row["calls"])
    return {
        "calls": calls,
        "spend": _num(row["spend"]),
        "input_tokens": int(row["input_tokens"]),
        "output_tokens": int(row["output_tokens"]),
        "errors": int(row["errors"]),
        "error_rate": row["errors"] / calls if calls else 0.0,
        "unpriced_calls": int(row["unpriced_calls"]),
        "p50_ms": _num(row["p50_ms"]),
        "p95_ms": _num(row["p95_ms"]),
        "avg_cost": _num(row["spend"]) / calls if calls else 0.0,
    }


# SpanAttributes also holds the prompt/completion bodies and ClickHouse reads the
# whole map column, so each query scans a lot of data. Cache briefly (a page load
# fires several queries and filter toggles repeat them). Cap runtime on the
# ClickHouse user (max_execution_time), since read-only users can't set it per query.
CACHE_TTL_S = 60
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def _query(sql: str, f: StatsFilters) -> list[dict[str, Any]]:
    # Prices are bound on every query that costs calls; they also key the cache so a price
    # refresh is picked up.
    params = {**f.params, **pricing.query_params()}
    key = json.dumps([sql, params], sort_keys=True, default=str)
    hit = _cache.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < CACHE_TTL_S:
        return hit[1]
    result = get_client().query(sql, parameters=params)
    rows = [dict(zip(result.column_names, row)) for row in result.result_rows]
    if len(_cache) > 200:
        _cache.clear()
    _cache[key] = (now, rows)
    return rows


def _group_rows(dim: str, f: StatsFilters) -> list[dict[str, Any]]:
    """Per-key metrics for a dimension, ordered by spend then calls."""
    sql = f"""
        SELECT {DIMENSION_EXPR[dim]} AS key, {STATS_AGGREGATES}
        FROM otel_traces
        WHERE {f.where_sql}
        GROUP BY key
        ORDER BY spend DESC, calls DESC
        LIMIT {MAX_GROUPS}
    """
    return [{"key": _label(r["key"]), **_metrics(r)} for r in _query(sql, f)]


@router.get("/summary")
def summary(f: StatsFilters = Depends(stats_filters)) -> dict[str, Any]:
    sql = f"SELECT {STATS_AGGREGATES} FROM otel_traces WHERE {f.where_sql}"
    rows = _query(sql, f)
    return _metrics(rows[0])


@router.get("/timeseries")
def timeseries(
    bucket: Bucket = "hour",
    group_by: Dimension | None = None,
    top: int = Query(6, ge=1, le=12),
    f: StatsFilters = Depends(stats_filters),
) -> dict[str, Any]:
    """Per-bucket metrics, optionally split by a dimension (top-N + Other)."""
    keys: list[str] = []
    key_expr = "''"
    if group_by:
        keys = [r["key"] for r in _group_rows(group_by, f)[:top]]
        raw_keys = ["" if k == NONE_LABEL else k for k in keys]
        f.params["top_keys"] = raw_keys
        key_expr = f"if({DIMENSION_EXPR[group_by]} IN {{top_keys:Array(String)}}, {DIMENSION_EXPR[group_by]}, '{OTHER_LABEL}')"
    sql = f"""
        SELECT toStartOfInterval(Timestamp, INTERVAL {BUCKET_INTERVALS[bucket]}) AS t,
               {key_expr} AS key, {STATS_AGGREGATES}
        FROM otel_traces
        WHERE {f.where_sql}
        GROUP BY t, key
        ORDER BY t
    """
    series = [
        {
            "t": r["t"].replace(tzinfo=None).isoformat() + "Z",
            "key": _label(r["key"]) if group_by else "total",
            **_metrics(r),
        }
        for r in _query(sql, f)
    ]
    present = {s["key"] for s in series}
    out_keys = keys + ([OTHER_LABEL] if OTHER_LABEL in present else []) if group_by else ["total"]
    return {"bucket": bucket, "group_by": group_by, "keys": out_keys, "series": series}


@router.get("/breakdown")
def breakdown(
    by: Dimension,
    limit: int = Query(10, ge=1, le=50),
    f: StatsFilters = Depends(stats_filters),
) -> dict[str, Any]:
    """Per-key metrics; keys beyond `limit` are rolled into one Other row."""
    rows = _group_rows(by, f)
    head, tail = rows[:limit], rows[limit:]
    if tail:
        calls = sum(r["calls"] for r in tail)
        spend = sum(r["spend"] for r in tail)
        errors = sum(r["errors"] for r in tail)
        head.append(
            {
                "key": OTHER_LABEL,
                "calls": calls,
                "spend": spend,
                "input_tokens": sum(r["input_tokens"] for r in tail),
                "output_tokens": sum(r["output_tokens"] for r in tail),
                "errors": errors,
                "error_rate": errors / calls if calls else 0.0,
                "unpriced_calls": sum(r["unpriced_calls"] for r in tail),
                "p50_ms": 0.0,
                "p95_ms": 0.0,
                "avg_cost": spend / calls if calls else 0.0,
                "other_count": len(tail),
            }
        )
    return {"by": by, "rows": head}


@router.get("/matrix")
def matrix(
    rows: Dimension = "feature_parent",
    cols: Dimension = "model",
    top_rows: int = Query(8, ge=1, le=20),
    top_cols: int = Query(6, ge=1, le=12),
    f: StatsFilters = Depends(stats_filters),
) -> dict[str, Any]:
    """Spend/calls cross-tab (e.g. feature x model); extras roll into Other."""
    if rows == cols:
        raise HTTPException(status_code=422, detail="rows and cols must differ")
    sql = f"""
        SELECT {DIMENSION_EXPR[rows]} AS r, {DIMENSION_EXPR[cols]} AS c, {STATS_AGGREGATES}
        FROM otel_traces
        WHERE {f.where_sql}
        GROUP BY r, c
        ORDER BY spend DESC, calls DESC
        LIMIT {MAX_GROUPS * 4}
    """
    data = _query(sql, f)

    def totals(axis: str) -> list[str]:
        acc: dict[str, tuple[float, int]] = {}
        for d in data:
            s, n = acc.get(d[axis], (0.0, 0))
            acc[d[axis]] = (s + _num(d["spend"]), n + int(d["calls"]))
        return [k for k, _ in sorted(acc.items(), key=lambda kv: kv[1], reverse=True)]

    row_keys = totals("r")[:top_rows]
    col_keys = totals("c")[:top_cols]
    cells: dict[tuple[str, str], dict[str, float]] = {}
    for d in data:
        r = d["r"] if d["r"] in row_keys else OTHER_LABEL
        c = d["c"] if d["c"] in col_keys else OTHER_LABEL
        cell = cells.setdefault((r, c), {"spend": 0.0, "calls": 0})
        cell["spend"] += _num(d["spend"])
        cell["calls"] += int(d["calls"])
    out_rows = [_label(k) for k in row_keys] + (
        [OTHER_LABEL] if any(r == OTHER_LABEL for r, _ in cells) else []
    )
    out_cols = [_label(k) for k in col_keys] + (
        [OTHER_LABEL] if any(c == OTHER_LABEL for _, c in cells) else []
    )
    return {
        "rows_by": rows,
        "cols_by": cols,
        "rows": out_rows,
        "cols": out_cols,
        "cells": [
            {"row": _label(r), "col": _label(c), **v} for (r, c), v in cells.items()
        ],
    }


@router.get("/dimensions")
def dimensions(f: StatsFilters = Depends(stats_filters)) -> dict[str, Any]:
    """Distinct values (with call counts) per dimension, for filter dropdowns."""
    pairs = ", ".join(f"('{d}', {DIMENSION_EXPR[d]})" for d in DIMENSION_EXPR)
    sql = f"""
        SELECT p.1 AS dim, p.2 AS val, count() AS n
        FROM (
            SELECT arrayJoin([{pairs}]) AS p
            FROM otel_traces
            WHERE {f.where_sql}
        )
        GROUP BY dim, val
        ORDER BY n DESC
    """
    out: dict[str, list[dict[str, Any]]] = {d: [] for d in DIMENSION_EXPR}
    for r in _query(sql, f):
        bucket = out[r["dim"]]
        if len(bucket) < 100:
            bucket.append({"value": _label(r["val"]), "calls": int(r["n"])})
    return {"dimensions": out}
