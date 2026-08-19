"""Cloudflare spend via the Billable Usage API (FOCUS-aligned).

GET /accounts/{account_id}/billable-usage returns daily charge periods with
ServiceName / ServiceFamilyName and a ContractedCost in BillingCurrency.

Two constraints from the API worth knowing before trusting the panel:

  * `from` must fall on the subscription's billing-cycle anchor day, so an
    arbitrary trailing-14d window is not directly requestable. We therefore
    ask for the *current billing period* (no date params) and filter to our
    window locally. Early in a cycle the window reaches back before the
    period start, and those days simply have no Cloudflare data -- fetch()
    reports the shortfall so the caller can log it rather than let the
    dashboard silently understate Cloudflare.
  * The API is self-serve accounts only; Enterprise support was still "in
    the works" at time of writing. An Enterprise account gets a 4xx here,
    which surfaces as a vendor error and leaves the rate card as the fallback.

Ref: https://blog.cloudflare.com/billable-usage-api/
"""
from __future__ import annotations

from datetime import date

from app.vendors._http import HttpError, get_json
from app.vendors.base import (
    ENV_SHARED,
    SOURCE_METERED,
    CostRow,
    VendorCostError,
    env_get,
)

PROVIDER = "cloudflare"
DEFAULT_API_BASE = "https://api.cloudflare.com/client/v4"
# Cloudflare's AI Gateway proxies model calls but does not bill the tokens
# (the model provider does, and app.vendors.llm already counts them from the
# gateway's own spans). Gateway *fees* are a real Cloudflare charge, so
# nothing is excluded here by default -- unlike Vercel, there is no overlap.
COST_FIELDS = ("ContractedCost", "BilledCost", "EffectiveCost")


def is_configured(env: dict[str, str] | None = None) -> bool:
    return bool(env_get(env, "CF_BILLING_TOKEN")) and bool(
        env_get(env, "CF_ACCOUNT_ID")
    )


def _cost_of(record: dict) -> float:
    """First populated FOCUS cost field, in preference order."""
    for field in COST_FIELDS:
        value = record.get(field)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return 0.0


def fetch_with_coverage(
    start: date, end: date, env: dict[str, str] | None = None
) -> tuple[list[CostRow], str]:
    """Return (rows, warning). warning is "" when the window is fully covered."""
    token = env_get(env, "CF_BILLING_TOKEN")
    account_id = env_get(env, "CF_ACCOUNT_ID")
    if not (token and account_id):
        raise VendorCostError("CF_BILLING_TOKEN and CF_ACCOUNT_ID are required")

    base = env_get(env, "CF_API_BASE", DEFAULT_API_BASE).rstrip("/")
    url = f"{base}/accounts/{account_id}/billable-usage"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    try:
        payload = get_json(url, headers)
    except HttpError as exc:
        raise VendorCostError(str(exc)) from exc

    result = payload.get("result")
    records = result if isinstance(result, list) else (result or {}).get("charges") or []

    rows: list[CostRow] = []
    earliest: str | None = None
    for record in records:
        day = str(record.get("ChargePeriodStart") or "")[:10]
        if not day:
            continue
        if earliest is None or day < earliest:
            earliest = day
        if not (start.isoformat() <= day < end.isoformat()):
            continue
        currency = str(record.get("BillingCurrency") or "USD").upper()
        if currency != "USD":
            raise VendorCostError(
                f"Cloudflare billed in {currency}; only USD is handled"
            )
        amount = _cost_of(record)
        if amount == 0:
            continue
        family = str(record.get("ServiceFamilyName") or "").strip()
        name = str(record.get("ServiceName") or "Unknown").strip()
        rows.append(
            CostRow(
                date=day,
                provider=PROVIDER,
                # Family disambiguates same-named SKUs across products
                # ("Standard" appears under both Workers and Images).
                service=f"{family} / {name}" if family and family != name else name,
                cost_usd=amount,
                source=SOURCE_METERED,
                env=ENV_SHARED,
            )
        )

    warning = ""
    if earliest and earliest > start.isoformat():
        warning = (
            f"billing period starts {earliest}; no Cloudflare data for "
            f"{start.isoformat()}..{earliest} (cycle anchor limits the window)"
        )
    return rows, warning


def fetch(
    start: date, end: date, env: dict[str, str] | None = None
) -> list[CostRow]:
    rows, _ = fetch_with_coverage(start, end, env)
    return rows
