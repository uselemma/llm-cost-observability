"""Azure Cost Management as a unified-cost provider.

Foundry / Azure OpenAI meters are published as saas.provider=azure_foundry so
the invoice can replace the derived llm/azure-openai token estimate. Every
other Azure service lands on saas.provider=azure. ChargeType Usage only --
credits cover the bill, they do not zero the cost of running the workload
(same reason AWS drops Credit/Refund).

Auth is an AAD app via client-credentials (Cost Management Reader). No Azure
SDK: token + query are two POSTs through app.vendors._http.

Ref: https://learn.microsoft.com/en-us/rest/api/cost-management/query
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from app.vendors._http import HttpError, post_form, post_json
from app.vendors.base import (
    ENV_DEV,
    ENV_PROD,
    SOURCE_METERED,
    CostRow,
    VendorCostError,
    env_get,
)

PROVIDER = "azure"
FOUNDRY_PROVIDER = "azure_foundry"
DEFAULT_LOGIN_BASE = "https://login.microsoftonline.com"
DEFAULT_MANAGEMENT_BASE = "https://management.azure.com"
TOKEN_SCOPE = "https://management.azure.com/.default"
QUERY_API_VERSION = "2023-11-01"
# Cost Management Daily + GroupBy is capped at 31 days; our default lookback
# is 14, but --since/--until can ask for more, so requests are chunked.
MAX_WINDOW_DAYS = 31
MAX_PAGES = 100
INCLUDED_CHARGE_TYPES = ("usage",)

# Substring match, case-insensitive, against Cost Management ServiceName.
# "foundry" also covers "Foundry Models"; the longer aliases are listed so a
# future rename that drops the word Foundry still classifies as Foundry.
FOUNDRY_SERVICE_MARKERS = (
    "foundry models",
    "azure openai",
    "cognitive services",
    "azure ai services",
    "foundry",
)

REQUIRED_ENV = (
    "AZURE_TENANT_ID",
    "AZURE_CLIENT_ID",
    "AZURE_CLIENT_SECRET",
    "AZURE_COST_SUBSCRIPTIONS",
)


@dataclass(frozen=True)
class AzureSubscription:
    name: str
    subscription_id: str


def is_configured(env: dict[str, str] | None = None) -> bool:
    return all(env_get(env, key) for key in REQUIRED_ENV)


def list_subscriptions(env: dict[str, str] | None = None) -> list[AzureSubscription]:
    """Parse AZURE_COST_SUBSCRIPTIONS as name:subscription-id pairs.

    Same shape as AWS_COST_ACCOUNTS: "prod:<id>,dev:<id>".
    """
    raw = env_get(env, "AZURE_COST_SUBSCRIPTIONS")
    subscriptions: list[AzureSubscription] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        name, _, subscription_id = part.partition(":")
        name = name.strip()
        subscription_id = subscription_id.strip()
        if not name or not subscription_id:
            raise VendorCostError(
                f"invalid AZURE_COST_SUBSCRIPTIONS entry {part!r}; "
                "expected name:subscription-id"
            )
        subscriptions.append(
            AzureSubscription(name=name, subscription_id=subscription_id)
        )
    if not subscriptions:
        raise VendorCostError("AZURE_COST_SUBSCRIPTIONS is empty")
    return subscriptions


def _env_for_subscription(name: str) -> str:
    return ENV_PROD if name.strip().lower() == "prod" else ENV_DEV


def _is_foundry(service_name: str) -> bool:
    lowered = service_name.lower()
    return any(marker in lowered for marker in FOUNDRY_SERVICE_MARKERS)


def _windows(start: date, end: date) -> list[tuple[date, date]]:
    """Split [start, end) into <=MAX_WINDOW_DAYS exclusive-end chunks."""
    chunks: list[tuple[date, date]] = []
    cursor = start
    while cursor < end:
        stop = min(cursor + timedelta(days=MAX_WINDOW_DAYS), end)
        chunks.append((cursor, stop))
        cursor = stop
    return chunks


def _query_body(start: date, end: date) -> dict[str, Any]:
    # Cost Management `to` is inclusive; our `end` is exclusive.
    last = end - timedelta(days=1)
    return {
        "type": "ActualCost",
        "timeframe": "Custom",
        "timePeriod": {"from": start.isoformat(), "to": last.isoformat()},
        "dataset": {
            "granularity": "Daily",
            "aggregation": {
                "totalCost": {"name": "Cost", "function": "Sum"}
            },
            # Max 2 groupings. ChargeType is a filter, not a group, so Usage
            # is dropped before pagination rather than after.
            "grouping": [
                {"type": "Dimension", "name": "ServiceName"},
                {"type": "Dimension", "name": "MeterSubCategory"},
            ],
            "filter": {
                "dimensions": {
                    "name": "ChargeType",
                    "operator": "In",
                    "values": ["Usage"],
                }
            },
        },
    }


def _column_index(columns: list[dict], *names: str) -> int | None:
    lowered = [str(col.get("name") or "").lower() for col in columns]
    for name in names:
        try:
            return lowered.index(name.lower())
        except ValueError:
            continue
    return None


def _parse_usage_date(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        text = str(int(value))
    else:
        text = str(value).strip()
    if len(text) >= 10 and text[4] == "-":
        return text[:10]
    digits = text[:8]
    if len(digits) == 8 and digits.isdigit():
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return ""


def _cell(row: list[Any], index: int | None, default: str = "") -> Any:
    if index is None or index < 0 or index >= len(row):
        return default
    value = row[index]
    return default if value is None else value


def rows_from_payload(payload: dict, subscription_name: str) -> list[CostRow]:
    """Map one Cost Management query page onto CostRows.

    Foundry meters -> azure_foundry / MeterSubCategory; everything else ->
    azure / ServiceName. Non-Usage ChargeType is dropped even if the API
    filter was omitted, so a mock (and a future API change) cannot sneak a
    refund into the total.
    """
    props = payload.get("properties") if isinstance(payload.get("properties"), dict) else payload
    columns = list(props.get("columns") or [])
    cost_idx = _column_index(columns, "CostUSD", "Cost", "PreTaxCost", "totalCost")
    date_idx = _column_index(columns, "UsageDate")
    service_idx = _column_index(columns, "ServiceName")
    meter_idx = _column_index(columns, "MeterSubCategory")
    charge_idx = _column_index(columns, "ChargeType")
    if cost_idx is None or date_idx is None:
        raise VendorCostError(
            "Cost Management response missing Cost/UsageDate columns"
        )

    env_name = _env_for_subscription(subscription_name)
    rows: list[CostRow] = []
    for raw in props.get("rows") or []:
        if not isinstance(raw, (list, tuple)):
            continue
        charge = str(_cell(raw, charge_idx)).strip().lower()
        if charge_idx is not None and charge not in INCLUDED_CHARGE_TYPES:
            continue
        amount = float(_cell(raw, cost_idx, 0) or 0)
        if amount == 0:
            continue
        day = _parse_usage_date(_cell(raw, date_idx))
        if not day:
            continue
        service_name = str(_cell(raw, service_idx) or "").strip() or "Unknown"
        meter = str(_cell(raw, meter_idx) or "").strip()
        if _is_foundry(service_name):
            provider = FOUNDRY_PROVIDER
            service = meter or service_name
        else:
            provider = PROVIDER
            service = service_name
        rows.append(
            CostRow(
                date=day,
                provider=provider,
                service=service,
                cost_usd=amount,
                source=SOURCE_METERED,
                env=env_name,
            )
        )
    return rows


def _access_token(env: dict[str, str] | None) -> str:
    tenant = env_get(env, "AZURE_TENANT_ID")
    client_id = env_get(env, "AZURE_CLIENT_ID")
    secret = env_get(env, "AZURE_CLIENT_SECRET")
    login = env_get(env, "AZURE_LOGIN_BASE", DEFAULT_LOGIN_BASE).rstrip("/")
    url = f"{login}/{tenant}/oauth2/v2.0/token"
    try:
        payload = post_form(
            url,
            {},
            {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": secret,
                "scope": TOKEN_SCOPE,
            },
        )
    except HttpError as exc:
        raise VendorCostError(f"Azure token request failed: {exc}") from exc
    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise VendorCostError("Azure token response had no access_token")
    return token


def _query_pages(
    url: str, headers: dict[str, str], body: dict[str, Any]
) -> list[dict]:
    pages: list[dict] = []
    next_url: str | None = url
    seen: set[str] = set()
    while next_url:
        if next_url in seen or len(pages) >= MAX_PAGES:
            raise VendorCostError(
                "Cost Management query pagination exceeded "
                f"{MAX_PAGES} pages or looped"
            )
        seen.add(next_url)
        try:
            payload = post_json(next_url, headers, body)
        except HttpError as exc:
            raise VendorCostError(f"Cost Management query failed: {exc}") from exc
        pages.append(payload)
        props = payload.get("properties") if isinstance(payload.get("properties"), dict) else payload
        nxt = str(props.get("nextLink") or payload.get("nextLink") or "").strip()
        next_url = nxt or None
    return pages


def _fetch_subscription(
    subscription: AzureSubscription,
    start: date,
    end: date,
    headers: dict[str, str],
    env: dict[str, str] | None,
) -> list[CostRow]:
    base = env_get(env, "AZURE_MANAGEMENT_BASE", DEFAULT_MANAGEMENT_BASE).rstrip("/")
    url = (
        f"{base}/subscriptions/{subscription.subscription_id}"
        f"/providers/Microsoft.CostManagement/query"
        f"?api-version={QUERY_API_VERSION}"
    )
    rows: list[CostRow] = []
    for window_start, window_end in _windows(start, end):
        body = _query_body(window_start, window_end)
        for page in _query_pages(url, headers, body):
            rows.extend(rows_from_payload(page, subscription.name))
    return rows


def fetch(
    start: date, end: date, env: dict[str, str] | None = None
) -> list[CostRow]:
    if not is_configured(env):
        raise VendorCostError(
            "AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, "
            "and AZURE_COST_SUBSCRIPTIONS are required"
        )
    subscriptions = list_subscriptions(env)
    token = _access_token(env)
    headers = {"Authorization": f"Bearer {token}"}

    rows: list[CostRow] = []
    errors: list[str] = []
    for subscription in subscriptions:
        try:
            rows.extend(_fetch_subscription(subscription, start, end, headers, env))
        except VendorCostError as exc:
            errors.append(f"{subscription.name}: {exc}")
    if errors and not rows:
        raise VendorCostError("; ".join(errors))
    return rows
