"""Shared vocabulary for per-vendor cost adapters.

Every vendor module in this package exposes the same trio -- PROVIDER,
is_configured(env), fetch(start, end, env) -> list[CostRow] -- so
app.export_saas_costs can iterate them without knowing what any individual
billing API looks like.

CostRow is deliberately shaped like the FinOps FOCUS spec's core columns
(ChargePeriodStart / ProviderName / ServiceName / BilledCost), because three
of our sources -- Vercel, Cloudflare, and AWS CUR -- already publish FOCUS
natively. Anything that isn't FOCUS (Cost Explorer's grouped response, the
ClickHouse Cloud usageCost records, our own LLM rollup) gets mapped into this
shape by its adapter rather than leaking its native schema onto the metric.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta

DEFAULT_LOOKBACK_DAYS = 14

# Cost attributed to running the product vs. building it. Only PROD feeds the
# headline $/trace -- dev spend is R&D, not cost of serving a trace -- but
# every row is still published so the breakdown panels can show both.
ENV_PROD = "prod"
ENV_DEV = "dev"
# Vendors billed as one account with no per-environment split (a single Vercel
# team, one Dash0 org). Rolled into the headline: the spend is incurred to
# serve prod even when a slice of it is really dev traffic.
ENV_SHARED = "shared"

# How a row's dollar figure was obtained. Kept as an attribute rather than a
# separate metric so a panel can total everything and still be able to show
# which fraction of that total is an invoice vs. an assumption.
SOURCE_METERED = "metered"  # pulled from the vendor's billing API
SOURCE_DERIVED = "derived"  # computed by us from telemetry (the LLM rollup)
SOURCE_DECLARED = "declared"  # a human-maintained rate card entry


class VendorCostError(Exception):
    """Raised when a vendor's cost data cannot be fetched."""


@dataclass(frozen=True)
class CostRow:
    """One vendor's spend for one service on one UTC day."""

    date: str  # ISO YYYY-MM-DD, the day the charge is attributed to
    provider: str  # "aws", "vercel", "cloudflare", ...
    service: str  # vendor's own service name, verbatim where possible
    cost_usd: float
    source: str = SOURCE_METERED
    env: str = ENV_SHARED

    def attributes(self) -> dict[str, str]:
        """OTLP attribute keys; PromQL sees these with underscores."""
        return {
            "saas.cost.date": self.date,
            "saas.provider": self.provider,
            "saas.service": self.service,
            "saas.cost.source": self.source,
            "saas.env": self.env,
        }


def parse_day(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError as exc:
        raise VendorCostError(f"invalid {field} date, expected YYYY-MM-DD") from exc


def resolve_range(
    since: str | None, until: str | None, lookback_days: int
) -> tuple[date, date]:
    """Return (inclusive start day, exclusive end day).

    Mirrors app.aws_costs.resolve_range so every vendor re-publishes the same
    window on the same run -- the dashboard's 25h last_over_time trick only
    reads consistently if all providers cover an identical span of days.
    """
    default_end = date.today() + timedelta(days=1)
    start = (
        parse_day(since, "since")
        if since
        else default_end - timedelta(days=max(1, lookback_days))
    )
    end = parse_day(until, "until") + timedelta(days=1) if until else default_end
    if end <= start:
        raise VendorCostError("until must be on or after since")
    return start, end


def env_get(env: dict[str, str] | None, key: str, default: str = "") -> str:
    e = env if env is not None else os.environ
    return (e.get(key) or default).strip()
