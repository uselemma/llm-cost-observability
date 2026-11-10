"""Shared time/dimension filter building for list + stats endpoints."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, Query

from app.span_queries import (
    DIMENSION_EXPR,
    FILTER_DIMENSIONS,
    SERVICE_FILTER,
)

NONE_LABEL = "(none)"


def parse_query_datetime(value: str, field_name: str) -> str:
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"invalid {field_name} datetime, expected ISO format",
        )
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def time_where(since: str | None, until: str | None) -> tuple[list[str], dict[str, Any]]:
    """Time-bounded predicates. Always bounded: defaults to the last 24h."""
    where: list[str] = []
    params: dict[str, Any] = {}
    if since:
        where.append("Timestamp >= {since:DateTime64(3)}")
        params["since"] = parse_query_datetime(since, "since")
    else:
        where.append("Timestamp >= now() - INTERVAL 24 HOUR")
    if until:
        where.append("Timestamp <= {until:DateTime64(3)}")
        params["until"] = parse_query_datetime(until, "until")
    return where, params


@dataclass
class StatsFilters:
    where_sql: str
    params: dict[str, Any] = field(default_factory=dict)


def stats_filters(
    since: str | None = None,
    until: str | None = None,
    model: list[str] = Query(default_factory=list),
    provider: list[str] = Query(default_factory=list),
    feature: list[str] = Query(default_factory=list),
    feature_parent: list[str] = Query(default_factory=list),
    prompt: list[str] = Query(default_factory=list),
    project_id: list[str] = Query(default_factory=list),
    variant: list[str] = Query(default_factory=list),
    status: list[str] = Query(default_factory=list),
    not_model: list[str] = Query(default_factory=list),
    not_provider: list[str] = Query(default_factory=list),
    not_feature: list[str] = Query(default_factory=list),
    not_feature_parent: list[str] = Query(default_factory=list),
    not_prompt: list[str] = Query(default_factory=list),
    not_project_id: list[str] = Query(default_factory=list),
    not_variant: list[str] = Query(default_factory=list),
    not_status: list[str] = Query(default_factory=list),
) -> StatsFilters:
    """FastAPI dependency. Include = IN, exclude (`not_<dim>`) = NOT IN.

    OR within a dimension, AND across dimensions. Untagged rows are `(none)`.
    """
    where, params = time_where(since, until)
    where.insert(0, SERVICE_FILTER)
    included = {
        "model": model,
        "provider": provider,
        "feature": feature,
        "feature_parent": feature_parent,
        "prompt": prompt,
        "project_id": project_id,
        "variant": variant,
        "status": status,
    }
    excluded = {
        "model": not_model,
        "provider": not_provider,
        "feature": not_feature,
        "feature_parent": not_feature_parent,
        "prompt": not_prompt,
        "project_id": not_project_id,
        "variant": not_variant,
        "status": not_status,
    }
    for dim in FILTER_DIMENSIONS:
        for op, values, prefix in (("IN", included[dim], "f"), ("NOT IN", excluded[dim], "x")):
            if not values:
                continue
            where.append(f"{DIMENSION_EXPR[dim]} {op} {{{prefix}_{dim}:Array(String)}}")
            params[f"{prefix}_{dim}"] = ["" if v == NONE_LABEL else v for v in values]
    return StatsFilters(" AND ".join(where), params)
