"""Vercel spend via the FOCUS v1.3 billing charges API.

GET /v1/billing/charges?from=&to=&teamId= streams JSONL, one FOCUS record per
(day, service). Because the schema is already FOCUS, the mapping here is
almost the identity function -- ServiceName -> service, BilledCost -> USD.

DOUBLE-COUNTING: Vercel bills model tokens routed through AI Gateway, and
that exact spend is *already* counted by app.vendors.llm (the reconciled
branch of the ENG-655 logical-call rollup takes Vercel's billed figure).
Publishing both would inflate LLM cost per trace by ~2x, so AI Gateway
charges are dropped here by default and the exporter logs what it dropped.
Override with VERCEL_EXCLUDE_SERVICES only if the LLM exporter is turned off.

Ref: https://vercel.com/docs/rest-api/billing/list-focus-billing-charges
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from urllib.parse import urlencode

from app.vendors._http import HttpError, get_jsonl
from app.vendors.base import (
    ENV_SHARED,
    SOURCE_METERED,
    CostRow,
    VendorCostError,
    env_get,
)

PROVIDER = "vercel"
DEFAULT_API_BASE = "https://api.vercel.com"
# Substring match, case-insensitive, against FOCUS ServiceName.
DEFAULT_EXCLUDED_SERVICES = ("ai gateway",)
# FOCUS ChargeCategory values worth counting as cost. Credits are negative
# adjustments and belong in the total; Tax is a real outflow. Purchase is
# excluded -- a prepaid commitment draws down over time and would otherwise
# spike a single day with money not yet consumed.
INCLUDED_CHARGE_CATEGORIES = ("Usage", "Credit", "Tax", "Adjustment")


def is_configured(env: dict[str, str] | None = None) -> bool:
    return bool(env_get(env, "VERCEL_BILLING_TOKEN")) and bool(
        env_get(env, "VERCEL_TEAM_ID")
    )


def excluded_services(env: dict[str, str] | None = None) -> tuple[str, ...]:
    raw = env_get(env, "VERCEL_EXCLUDE_SERVICES")
    if not raw:
        return DEFAULT_EXCLUDED_SERVICES
    if raw.lower() in ("-", "none", "off"):
        return ()
    return tuple(part.strip().lower() for part in raw.split(",") if part.strip())


def _iso_utc(day: date) -> str:
    return datetime.combine(day, time.min, tzinfo=timezone.utc).isoformat()


def fetch(
    start: date, end: date, env: dict[str, str] | None = None
) -> list[CostRow]:
    token = env_get(env, "VERCEL_BILLING_TOKEN")
    team_id = env_get(env, "VERCEL_TEAM_ID")
    if not (token and team_id):
        raise VendorCostError("VERCEL_BILLING_TOKEN and VERCEL_TEAM_ID are required")

    base = env_get(env, "VERCEL_API_BASE", DEFAULT_API_BASE).rstrip("/")
    skip = excluded_services(env)
    # `to` is exclusive, which is exactly how `end` is defined.
    query = urlencode(
        {"from": _iso_utc(start), "to": _iso_utc(end), "teamId": team_id}
    )
    url = f"{base}/v1/billing/charges?{query}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/jsonl"}

    rows: list[CostRow] = []
    try:
        for record in get_jsonl(url, headers):
            category = str(record.get("ChargeCategory") or "Usage")
            if category not in INCLUDED_CHARGE_CATEGORIES:
                continue
            service = str(record.get("ServiceName") or "Unknown")
            if any(marker in service.lower() for marker in skip):
                continue
            amount = float(record.get("BilledCost") or 0)
            if amount == 0:
                continue
            day = str(record.get("ChargePeriodStart") or "")[:10]
            if not day:
                continue
            rows.append(
                CostRow(
                    date=day,
                    provider=PROVIDER,
                    service=service,
                    cost_usd=amount,
                    source=SOURCE_METERED,
                    # One Vercel team funds preview and production
                    # deployments alike; there is no per-env invoice to split.
                    env=ENV_SHARED,
                )
            )
    except HttpError as exc:
        raise VendorCostError(str(exc)) from exc
    return rows
