"""AWS as a unified-cost provider: Cost Explorer daily spend by service.

Thin adapter over app.aws_costs (which already owns the multi-account
assume-role dance and partial-failure handling). The only new logic here is
mapping the configured account *name* onto the env dimension, so the
dashboard can separate cost of serving from cost of building.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.aws_costs import AwsCostError, get_daily_costs
from app.vendors.base import (
    ENV_DEV,
    ENV_PROD,
    SOURCE_METERED,
    CostRow,
    VendorCostError,
)

PROVIDER = "aws"


def is_configured(env: dict[str, str] | None = None) -> bool:
    """Always on: credentials come from IRSA, not a named env var."""
    return True


def _env_for_account(account_name: str) -> str:
    return ENV_PROD if account_name.strip().lower() == "prod" else ENV_DEV


def fetch(
    start: date, end: date, env: dict[str, str] | None = None
) -> list[CostRow]:
    try:
        payload = get_daily_costs(
            since=start.isoformat(),
            # get_daily_costs takes an *inclusive* until; end is exclusive.
            until=(end - timedelta(days=1)).isoformat(),
            env=env,
        )
    except AwsCostError as exc:
        raise VendorCostError(str(exc)) from exc

    rows = [
        CostRow(
            date=str(row["date"]),
            provider=PROVIDER,
            service=str(row["service"]),
            cost_usd=float(row["amount_usd"]),
            source=SOURCE_METERED,
            env=_env_for_account(str(row["account_name"])),
        )
        for row in payload["rows"]
    ]
    # Per-account failures are already tolerated upstream (one broken
    # assume-role must not drop the account that worked); surface them as a
    # partial result rather than swallowing them entirely.
    if payload["errors"] and not rows:
        raise VendorCostError("; ".join(payload["errors"]))
    return rows
