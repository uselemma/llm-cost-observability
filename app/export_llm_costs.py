"""CLI: aggregate daily LLM spend from ClickHouse and publish gauges to Dash0.

Publishes two gauges per (day, model, provider, feature) row of the logical-
call rollup (app.llm_costs):

  llm.cost.estimated  — daily USD spend (Vercel billed cost for reconciled
                        calls, Cloudflare estimate for legacy calls)
  llm.calls           — successful logical calls

Attribute keys (PromQL label names use underscores): llm.cost.date,
gen_ai.request.model, gen_ai.provider.name, feature. Each run re-publishes a
rolling lookback window; identical attribute sets update in place, so chart
with last_over_time (same pattern as aws.cost.unblended).

Usage:
  python -m app.export_llm_costs
  python -m app.export_llm_costs --dry-run --lookback-days 3
  python -m app.export_llm_costs --since 2026-07-01 --until 2026-08-01

Env: LLM_CLICKHOUSE_* (see app.ch), DASH0_INGESTION_URL ("off" disables),
DASH0_INGESTION_KEY or DASH0_TOKEN, DASH0_DATASET (default production),
LLM_COST_LOOKBACK_DAYS, OTEL_SERVICE_NAME (default llm-cost-exporter).
"""
from __future__ import annotations

import logging
import sys
from collections.abc import Sequence

from app.cost_export import run_export
from app.dash0_export import GaugeSpec, PublishResult, publish_gauges
from app.llm_costs import DEFAULT_LOOKBACK_DAYS, LlmCostRow, get_daily_costs

COST_METRIC = "llm.cost.estimated"
CALLS_METRIC = "llm.calls"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("export_llm_costs")


def publish_llm_cost_gauges(rows: Sequence[LlmCostRow]) -> PublishResult:
    specs = [
        GaugeSpec(
            name=COST_METRIC,
            unit="USD",
            description=(
                "Daily LLM spend by model, provider, and feature "
                "(billed for reconciled calls, estimated for legacy)"
            ),
            points=[(row.spend_usd, row.gauge_attributes()) for row in rows],
        ),
        GaugeSpec(
            name=CALLS_METRIC,
            unit="{call}",
            description=(
                "Daily successful logical LLM calls by model, provider, and feature"
            ),
            points=[(float(row.calls), row.gauge_attributes()) for row in rows],
        ),
    ]
    return publish_gauges(specs, default_service_name="llm-cost-exporter")


def main(argv: list[str] | None = None) -> int:
    return run_export(
        argv,
        description=__doc__,
        lookback_env="LLM_COST_LOOKBACK_DAYS",
        default_lookback=DEFAULT_LOOKBACK_DAYS,
        dry_run_help="Query ClickHouse only; do not export to Dash0",
        fetch_failed="clickhouse spend query failed",
        fetch=get_daily_costs,
        format_row=lambda row: (
            f"dry-run {row.date} {row.provider}/{row.model} {row.feature} "
            f"${row.spend_usd:.4f} ({row.calls} calls)"
        ),
        publish=publish_llm_cost_gauges,
        published_label=f"{COST_METRIC} / {CALLS_METRIC}",
        log=log,
    )


if __name__ == "__main__":
    sys.exit(main())
