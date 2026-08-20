"""CLI: publish unified per-vendor SaaS spend to Dash0 as two gauges.

  saas.cost.daily         -- daily USD cost, one point per (date, provider,
                             service); use for window totals
  saas.cost.daily.current -- the same figures for the most recent complete
                             day only, carrying no date attribute; use for
                             per-vendor daily trend charts

Attribute keys (PromQL label names use underscores): saas.cost.date,
saas.provider, saas.service, saas.cost.source, saas.env. Each run
re-publishes a rolling lookback window; identical attribute sets update in
place, so chart with last_over_time (see the dashboard's 25h comment).

The dated gauge cannot be charted as a daily trend -- grouping by the date
attribute gives one series per vendor per day, and the date cannot reach the
x-axis because Dash0 drops backdated samples. Hence the .current companion;
see app.dash0_export.latest_complete_day_spec.

This supersedes export_aws_costs / export_llm_costs as the dashboard's
source. Those two keep running and keep publishing their own metrics -- the
existing cost-per-trace panels still read them -- but everything they cover
is also represented here under saas.provider="aws" / "llm/*".

A vendor that is not configured is skipped, not failed: rollout is per-vendor
by adding credentials, with no code change. A vendor that IS configured but
errors leaves the others intact and sets a non-zero exit only if nothing at
all published.

Usage:
  python -m app.export_saas_costs
  python -m app.export_saas_costs --dry-run --lookback-days 3
  python -m app.export_saas_costs --vendors aws,clickhouse_cloud
  python -m app.export_saas_costs --since 2026-07-01 --until 2026-08-01

Env: SAAS_COST_LOOKBACK_DAYS, SAAS_COST_VENDORS (comma list; default all
configured), plus each vendor's own credentials -- see app/vendors/*.py.
Dash0: DASH0_INGESTION_URL ("off" disables), DASH0_INGESTION_KEY or
DASH0_TOKEN, DASH0_DATASET (default production), OTEL_SERVICE_NAME.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import defaultdict
from datetime import date, timedelta

from app.dash0_export import (
    CURRENT_DAY_SUFFIX,
    GaugeSpec,
    PublishResult,
    latest_complete_day_spec,
    publish_gauges,
)
from app.vendors import VENDORS
from app.vendors import cloudflare as cloudflare_vendor
from app.vendors import declared as declared_vendor
from app.vendors.base import (
    DEFAULT_LOOKBACK_DAYS,
    CostRow,
    VendorCostError,
    resolve_range,
)

METRIC_NAME = "saas.cost.daily"
SERVICE_NAME = "saas-cost-exporter"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("export_saas_costs")


def select_vendors(
    requested: str | None, env: dict[str, str] | None = None
) -> tuple[list[str], list[str]]:
    """Return (names to run, names skipped for missing configuration).

    An explicitly requested vendor is run even if unconfigured, so a typo or
    a missing secret fails loudly instead of silently exporting nothing.
    """
    raw = (requested or "").strip()
    if raw:
        names = [part.strip() for part in raw.split(",") if part.strip()]
        unknown = [name for name in names if name not in VENDORS]
        if unknown:
            raise SystemExit(
                f"unknown vendor(s): {', '.join(unknown)}; "
                f"known: {', '.join(sorted(VENDORS))}"
            )
        return names, []

    selected, skipped = [], []
    for name, module in VENDORS.items():
        if module.is_configured(env):
            selected.append(name)
        else:
            skipped.append(name)
    return selected, skipped


def collect(
    names: list[str],
    start: date,
    end: date,
    env: dict[str, str] | None = None,
) -> tuple[list[CostRow], list[str], list[str]]:
    """Run each vendor; return (rows, errors, warnings)."""
    rows: list[CostRow] = []
    errors: list[str] = []
    warnings: list[str] = []

    for name in names:
        module = VENDORS[name]
        try:
            if module is cloudflare_vendor:
                # Cloudflare can only serve the current billing period, so it
                # reports how much of our window it actually covered.
                vendor_rows, warning = module.fetch_with_coverage(start, end, env)
                if warning:
                    warnings.append(f"{name}: {warning}")
            else:
                vendor_rows = module.fetch(start, end, env)
        except VendorCostError as exc:
            errors.append(f"{name}: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 — one vendor must not sink the run
            errors.append(f"{name}: unexpected {type(exc).__name__}: {exc}")
            continue

        rows.extend(vendor_rows)
        total = sum(row.cost_usd for row in vendor_rows)
        log.info("%s: %d rows, $%.2f over window", name, len(vendor_rows), total)

    if declared_vendor.PROVIDER in names or any(
        row.source == "declared" for row in rows
    ):
        try:
            missing = declared_vendor.unpriced(env)
        except VendorCostError as exc:
            warnings.append(f"declared: {exc}")
        else:
            if missing:
                warnings.append(
                    "rate card has no monthly_usd for: "
                    f"{', '.join(missing)} — total understates spend"
                )
    return rows, errors, warnings


def aggregate(rows: list[CostRow]) -> list[tuple[float, dict[str, str]]]:
    """Sum duplicate attribute sets into one point each.

    Vendors legitimately emit several records for the same (day, service) --
    ClickHouse per entity, Cloudflare per zone. OTLP would keep only the last
    value written for an identical attribute set, so pre-summing here is what
    prevents a silent undercount.
    """
    totals: dict[tuple[tuple[str, str], ...], float] = defaultdict(float)
    for row in rows:
        totals[tuple(sorted(row.attributes().items()))] += row.cost_usd
    return [
        (value, dict(key))
        for key, value in sorted(totals.items())
        if value != 0
    ]


def publish_saas_cost_gauges(
    rows: list[CostRow], *, env: dict[str, str] | None = None
) -> PublishResult:
    spec = GaugeSpec(
        name=METRIC_NAME,
        unit="USD",
        description=(
            "Daily SaaS spend by provider and service (metered from vendor "
            "billing APIs, derived from telemetry, or declared in the rate card)"
        ),
        points=aggregate(rows),
    )
    specs = [spec]
    current = latest_complete_day_spec(spec, date_key="saas.cost.date")
    if current is None:
        log.warning(
            "no complete day in window; %s%s not published",
            METRIC_NAME,
            CURRENT_DAY_SUFFIX,
        )
    else:
        specs.append(current)
    return publish_gauges(specs, service_name=SERVICE_NAME, env=env)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", help="Inclusive start date YYYY-MM-DD")
    parser.add_argument("--until", help="Inclusive end date YYYY-MM-DD")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=int(os.environ.get("SAAS_COST_LOOKBACK_DAYS", DEFAULT_LOOKBACK_DAYS)),
        help=f"Days to fetch when --since/--until omitted (default {DEFAULT_LOOKBACK_DAYS})",
    )
    parser.add_argument(
        "--vendors",
        default=os.environ.get("SAAS_COST_VENDORS", ""),
        help="Comma-separated vendor names (default: every configured vendor)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch vendor costs only; do not export to Dash0",
    )
    args = parser.parse_args(argv)

    try:
        start, end = resolve_range(args.since, args.until, args.lookback_days)
    except VendorCostError as exc:
        log.error("%s", exc)
        return 1

    names, skipped = select_vendors(args.vendors)
    if skipped:
        log.info("skipping unconfigured vendors: %s", ", ".join(skipped))
    if not names:
        log.error("no vendors configured; nothing to export")
        return 1

    rows, errors, warnings = collect(names, start, end)
    for warning in warnings:
        log.warning("%s", warning)

    log.info(
        "fetched %d rows from %d vendor(s) (%s .. %s); vendor errors=%s",
        len(rows),
        len(names),
        start.isoformat(),
        (end - timedelta(days=1)).isoformat(),
        "; ".join(errors) or "none",
    )

    if args.dry_run:
        by_provider: dict[str, float] = defaultdict(float)
        for row in rows:
            by_provider[row.provider] += row.cost_usd
        for provider, total in sorted(
            by_provider.items(), key=lambda item: -item[1]
        ):
            log.info("dry-run %-20s $%10.2f", provider, total)
        log.info("dry-run TOTAL $%.2f over %d days", sum(by_provider.values()), (end - start).days)
        return 1 if errors and not rows else 0

    if not rows:
        log.error("no cost rows collected; errors=%s", "; ".join(errors) or "none")
        return 1

    result = publish_saas_cost_gauges(rows)
    if not result.ok:
        log.error("dash0 export failed: %s", result.reason)
        return 1

    log.info("published %d %s points to Dash0", result.points, METRIC_NAME)
    if errors:
        log.warning("partial vendor failures: %s", "; ".join(errors))
    return 0


if __name__ == "__main__":
    sys.exit(main())
