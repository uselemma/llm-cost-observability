"""Flat-fee / no-API vendors, from a checked-in rate card.

Vendors like Dash0 and Clerk bill monthly with no usage-cost endpoint we can
call, so their spend is declared in rate_card.yaml and amortized evenly
across the requested window. Rows carry SOURCE_DECLARED so a dashboard can
always separate "this is an invoice" from "this is what we told it".

Entries with monthly_usd: null are reported as unpriced instead of being
guessed at -- see unpriced() and the exporter's warning line.
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any

import yaml

from app.vendors.base import (
    ENV_SHARED,
    SOURCE_DECLARED,
    CostRow,
    VendorCostError,
    env_get,
)

PROVIDER = "declared"
DEFAULT_RATE_CARD = os.path.join(os.path.dirname(__file__), "rate_card.yaml")
# Monthly invoice spread over an average calendar month.
DAYS_PER_MONTH = 365.0 / 12.0
VALID_ENVS = ("prod", "dev", "shared")


def is_configured(env: dict[str, str] | None = None) -> bool:
    return os.path.exists(_rate_card_path(env))


def _rate_card_path(env: dict[str, str] | None = None) -> str:
    return env_get(env, "SAAS_RATE_CARD_PATH") or DEFAULT_RATE_CARD


def load_rate_card(env: dict[str, str] | None = None) -> list[dict[str, Any]]:
    path = _rate_card_path(env)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            document = yaml.safe_load(handle) or {}
    except OSError as exc:
        raise VendorCostError(f"cannot read rate card {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise VendorCostError(f"invalid YAML in rate card {path}: {exc}") from exc

    entries = document.get("vendors")
    if entries is None:
        raise VendorCostError(f"rate card {path} has no 'vendors' list")
    if not isinstance(entries, list):
        raise VendorCostError(f"rate card {path}: 'vendors' must be a list")

    for entry in entries:
        if not isinstance(entry, dict):
            raise VendorCostError(f"rate card {path}: each vendor must be a mapping")
        for field in ("provider", "service"):
            if not str(entry.get(field) or "").strip():
                raise VendorCostError(f"rate card {path}: vendor missing {field}")
        vendor_env = str(entry.get("env") or ENV_SHARED).strip()
        if vendor_env not in VALID_ENVS:
            raise VendorCostError(
                f"rate card {path}: {entry['provider']} has env={vendor_env!r}, "
                f"expected one of {', '.join(VALID_ENVS)}"
            )
        amount = entry.get("monthly_usd")
        if amount is not None:
            try:
                value = float(amount)
            except (TypeError, ValueError) as exc:
                raise VendorCostError(
                    f"rate card {path}: {entry['provider']} monthly_usd "
                    f"{amount!r} is not a number"
                ) from exc
            if value < 0:
                raise VendorCostError(
                    f"rate card {path}: {entry['provider']} monthly_usd is negative"
                )
    return entries


def unpriced(env: dict[str, str] | None = None) -> list[str]:
    """Providers present in the rate card but still missing a figure."""
    return [
        str(entry["provider"])
        for entry in load_rate_card(env)
        if entry.get("monthly_usd") is None
    ]


def fetch(
    start: date, end: date, env: dict[str, str] | None = None
) -> list[CostRow]:
    entries = load_rate_card(env)
    days = [start + timedelta(days=offset) for offset in range((end - start).days)]

    rows: list[CostRow] = []
    for entry in entries:
        amount = entry.get("monthly_usd")
        if amount is None:
            continue  # unpriced -- surfaced via unpriced(), never guessed
        daily = float(amount) / DAYS_PER_MONTH
        if daily == 0:
            continue
        for day in days:
            rows.append(
                CostRow(
                    date=day.isoformat(),
                    provider=str(entry["provider"]).strip(),
                    service=str(entry["service"]).strip(),
                    cost_usd=daily,
                    source=SOURCE_DECLARED,
                    env=str(entry.get("env") or ENV_SHARED).strip(),
                )
            )
    return rows
