"""ClickHouse Cloud spend via the organization usageCost API.

GET /v1/organizations/{orgId}/usageCost?from_date=&to_date= returns one
record per (day, entity), where an entity is a data warehouse, a service, or
a ClickPipe. Costs are denominated in ClickHouse Credits (CHC); the standard
contract defines 1 CHC = 1 USD, which is what CHC_USD defaults to. A committed
-spend contract with a negotiated rate should override it rather than have the
dashboard quietly report list price.

Ref: https://clickhouse.com/docs/cloud/manage/api (Billing tag)
"""
from __future__ import annotations

from datetime import date, timedelta
from base64 import b64encode
from urllib.parse import urlencode

from app.vendors._http import HttpError, get_json
from app.vendors.base import (
    ENV_PROD,
    SOURCE_METERED,
    CostRow,
    VendorCostError,
    env_get,
)

PROVIDER = "clickhouse_cloud"
DEFAULT_API_BASE = "https://api.clickhouse.cloud"
# The API caps a single request at 30 days; our default window is 14, but
# --since/--until can ask for more, so requests are chunked.
MAX_WINDOW_DAYS = 30
DEFAULT_CHC_USD = 1.0

# metrics{} keys -> the service label we publish. Splitting the record into
# its cost components is what makes this a *per-service* breakdown rather
# than one opaque "ClickHouse Cloud" number.
METRIC_SERVICES = {
    "computeCHC": "Compute",
    "storageCHC": "Storage",
    "backupCHC": "Backup",
    "dataTransferCHC": "Data transfer",
    "initialLoadCHC": "ClickPipe initial load",
    "publicDataTransferCHC": "Public data transfer",
    "interRegionTier1DataTransferCHC": "Inter-region transfer (tier 1)",
    "interRegionTier2DataTransferCHC": "Inter-region transfer (tier 2)",
    "interRegionTier3DataTransferCHC": "Inter-region transfer (tier 3)",
    "interRegionTier4DataTransferCHC": "Inter-region transfer (tier 4)",
}


def is_configured(env: dict[str, str] | None = None) -> bool:
    return all(
        env_get(env, key)
        for key in (
            "CLICKHOUSE_CLOUD_ORG_ID",
            "CLICKHOUSE_CLOUD_KEY_ID",
            "CLICKHOUSE_CLOUD_KEY_SECRET",
        )
    )


def _chc_usd(env: dict[str, str] | None) -> float:
    raw = env_get(env, "CLICKHOUSE_CLOUD_CHC_USD")
    if not raw:
        return DEFAULT_CHC_USD
    try:
        return float(raw)
    except ValueError as exc:
        raise VendorCostError(
            f"invalid CLICKHOUSE_CLOUD_CHC_USD {raw!r}; expected a number"
        ) from exc


def _windows(start: date, end: date) -> list[tuple[date, date]]:
    """Split [start, end) into <=MAX_WINDOW_DAYS inclusive from/to pairs."""
    chunks: list[tuple[date, date]] = []
    cursor = start
    while cursor < end:
        stop = min(cursor + timedelta(days=MAX_WINDOW_DAYS), end)
        chunks.append((cursor, stop - timedelta(days=1)))
        cursor = stop
    return chunks


def _rows_from_record(record: dict, chc_usd: float) -> list[CostRow]:
    day = str(record.get("date") or "")[:10]
    if not day:
        return []
    entity = str(record.get("entityName") or record.get("entityType") or "unknown")
    metrics = record.get("metrics") or {}

    rows: list[CostRow] = []
    accounted = 0.0
    for key, label in METRIC_SERVICES.items():
        amount = float(metrics.get(key) or 0)
        if amount == 0:
            continue
        accounted += amount
        rows.append(
            CostRow(
                date=day,
                provider=PROVIDER,
                service=f"{label} ({entity})",
                cost_usd=amount * chc_usd,
                source=SOURCE_METERED,
                env=ENV_PROD,
            )
        )

    # Guard against a new CHC component appearing in the API that this map
    # doesn't know about: totalCHC is authoritative, so any unexplained
    # remainder is published rather than silently dropped from the total.
    remainder = float(record.get("totalCHC") or 0) - accounted
    if abs(remainder) > 1e-9:
        rows.append(
            CostRow(
                date=day,
                provider=PROVIDER,
                service=f"Other ({entity})",
                cost_usd=remainder * chc_usd,
                source=SOURCE_METERED,
                env=ENV_PROD,
            )
        )
    return rows


def fetch(
    start: date, end: date, env: dict[str, str] | None = None
) -> list[CostRow]:
    org_id = env_get(env, "CLICKHOUSE_CLOUD_ORG_ID")
    key_id = env_get(env, "CLICKHOUSE_CLOUD_KEY_ID")
    key_secret = env_get(env, "CLICKHOUSE_CLOUD_KEY_SECRET")
    if not (org_id and key_id and key_secret):
        raise VendorCostError(
            "CLICKHOUSE_CLOUD_ORG_ID / _KEY_ID / _KEY_SECRET are required"
        )

    base = env_get(env, "CLICKHOUSE_CLOUD_API_BASE", DEFAULT_API_BASE).rstrip("/")
    token = b64encode(f"{key_id}:{key_secret}".encode()).decode()
    headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}
    chc_usd = _chc_usd(env)

    rows: list[CostRow] = []
    for from_date, to_date in _windows(start, end):
        query = urlencode(
            {"from_date": from_date.isoformat(), "to_date": to_date.isoformat()}
        )
        url = f"{base}/v1/organizations/{org_id}/usageCost?{query}"
        try:
            payload = get_json(url, headers)
        except HttpError as exc:
            raise VendorCostError(str(exc)) from exc
        for record in (payload.get("result") or {}).get("costs") or []:
            rows.extend(_rows_from_record(record, chc_usd))
    return rows
