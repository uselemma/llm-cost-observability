"""CLI: aggregate daily LLM spend from ClickHouse and publish gauges to Dash0.

Publishes gauges per (day, model, provider, feature) row of the logical-call
rollup (app.llm_costs):

  llm.cost.estimated          -- daily USD spend (Vercel billed cost for
                                 reconciled calls, Cloudflare estimate for
                                 legacy calls). Use for window totals.
  llm.calls                   -- successful logical calls
  llm.cost.estimated.current  -- spend for the most recent complete day only,
                                 carrying no date attribute. Use for per-model
                                 daily trend charts.

Attribute keys (PromQL label names use underscores): llm.cost.date,
gen_ai.request.model, gen_ai.provider.name, feature. Each run re-publishes a
rolling lookback window; identical attribute sets update in place, so chart
with last_over_time.

The dated gauge cannot be charted as a daily trend -- grouping by the date
attribute gives one series per model per day, and the date cannot reach the
x-axis because Dash0 drops backdated samples. Hence the .current companion;
see app.dash0_export.latest_complete_day_spec.

Usage:
  python -m app.export_llm_costs
  python -m app.export_llm_costs --dry-run --lookback-days 3
  python -m app.export_llm_costs --since 2026-07-01 --until 2026-08-01

Env: LLM_CLICKHOUSE_* (see app.ch), LLM_COST_LOOKBACK_DAYS,
DASH0_INGESTION_URL ("off" disables), DASH0_INGESTION_KEY or DASH0_TOKEN,
DASH0_DATASET (default production), OTEL_SERVICE_NAME.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from app.dash0_export import (
    CURRENT_DAY_SUFFIX,
    GaugeSpec,
    PublishResult,
    latest_complete_day_spec,
    publish_gauges,
)
from app.llm_costs import DEFAULT_LOOKBACK_DAYS, LlmCostError, get_daily_costs

COST_METRIC = "llm.cost.estimated"
CALLS_METRIC = "llm.calls"
SERVICE_NAME = "llm-cost-exporter"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("export_llm_costs")


def publish_llm_cost_gauges(
    rows: list[dict], *, env: dict[str, str] | None = None
) -> PublishResult:
    def attrs(row: dict) -> dict[str, str]:
        return {
            "llm.cost.date": str(row["date"]),
            "gen_ai.request.model": str(row["model"]),
            "gen_ai.provider.name": str(row["provider"]),
            "feature": str(row["feature"]),
        }

    cost_spec = GaugeSpec(
        name=COST_METRIC,
        unit="USD",
        description=(
            "Daily LLM spend by model, provider, and feature "
            "(billed for reconciled calls, estimated for legacy)"
        ),
        points=[(float(row["spend_usd"]), attrs(row)) for row in rows],
    )
    specs = [
        cost_spec,
        GaugeSpec(
            name=CALLS_METRIC,
            unit="{call}",
            description=(
                "Daily successful logical LLM calls by model, provider, and feature"
            ),
            points=[(float(row["calls"]), attrs(row)) for row in rows],
        ),
    ]
    # Only spend gets a trend companion; the call-count panels are ratios
    # against the window total, not per-day lines.
    current = latest_complete_day_spec(cost_spec, date_key="llm.cost.date")
    if current is None:
        log.warning(
            "no complete day in window; %s%s not published",
            COST_METRIC,
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
        default=int(os.environ.get("LLM_COST_LOOKBACK_DAYS", DEFAULT_LOOKBACK_DAYS)),
        help=f"Days to fetch when --since/--until omitted (default {DEFAULT_LOOKBACK_DAYS})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Query ClickHouse only; do not export to Dash0",
    )
    args = parser.parse_args(argv)

    try:
        payload = get_daily_costs(
            since=args.since, until=args.until, lookback_days=args.lookback_days
        )
    except LlmCostError as exc:
        log.error("clickhouse spend query failed: %s", exc)
        return 1

    rows = payload["rows"]
    log.info(
        "fetched %d rows (%s .. %s)", len(rows), payload["since"], payload["until"]
    )

    if args.dry_run:
        for row in rows[:20]:
            log.info(
                "dry-run %s %s/%s %s $%.4f (%d calls)",
                row["date"],
                row["provider"],
                row["model"],
                row["feature"],
                row["spend_usd"],
                row["calls"],
            )
        if len(rows) > 20:
            log.info("... %d more rows", len(rows) - 20)
        return 0

    result = publish_llm_cost_gauges(rows)
    if not result.ok:
        log.error("dash0 export failed: %s", result.reason)
        return 1

    log.info(
        "published %d %s / %s points to Dash0",
        result.points,
        COST_METRIC,
        CALLS_METRIC,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
