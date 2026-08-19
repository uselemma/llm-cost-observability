"""Per-vendor cost adapters behind one interface (see base.CostRow).

VENDORS is the registry app.export_saas_costs iterates. Adding a vendor means
writing a module with PROVIDER / is_configured / fetch and appending it here;
nothing else in the exporter needs to change.
"""
from __future__ import annotations

from app.vendors import (
    aws,
    clickhouse_cloud,
    cloudflare,
    declared,
    llm,
    vercel,
)
from app.vendors.base import (  # re-exported for convenience
    DEFAULT_LOOKBACK_DAYS,
    CostRow,
    VendorCostError,
    resolve_range,
)

VENDORS = {
    "aws": aws,
    "llm": llm,
    "clickhouse_cloud": clickhouse_cloud,
    "cloudflare": cloudflare,
    "vercel": vercel,
    "declared": declared,
}

__all__ = [
    "VENDORS",
    "CostRow",
    "VendorCostError",
    "DEFAULT_LOOKBACK_DAYS",
    "resolve_range",
]
