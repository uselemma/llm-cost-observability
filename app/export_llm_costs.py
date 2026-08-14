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

from app.cost_export import DEFAULT_LOOKBACK_DAYS, GaugeBinding, run_export
from app.llm_costs import LlmCostRow, get_daily_costs

COST_METRIC = "llm.cost.estimated"
CALLS_METRIC = "llm.calls"
SERVICE_NAME = "llm-cost-exporter"
log = logging.getLogger("export_llm_costs")


def llm_cost_attributes(row: LlmCostRow) -> dict[str, str]:
    return {
        "llm.cost.date": row.date,
        "gen_ai.request.model": row.model,
        "gen_ai.provider.name": row.provider,
        "feature": row.feature,
    }


def _format_row(row: LlmCostRow) -> str:
    return (
        f"dry-run {row.date} {row.provider}/{row.model} {row.feature} "
        f"${row.spend_usd:.4f} ({row.calls} calls)"
    )


LLM_COST_GAUGES: tuple[GaugeBinding[LlmCostRow], ...] = (
    GaugeBinding(
        name=COST_METRIC,
        unit="USD",
        description=(
            "Daily LLM spend by model, provider, and feature "
            "(billed for reconciled calls, estimated for legacy)"
        ),
        value=lambda row: row.spend_usd,
    ),
    GaugeBinding(
        name=CALLS_METRIC,
        unit="{call}",
        description=(
            "Daily successful logical LLM calls by model, provider, and feature"
        ),
        value=lambda row: float(row.calls),
    ),
)


def main(argv: list[str] | None = None) -> int:
    return run_export(
        argv,
        description=__doc__,
        lookback_env="LLM_COST_LOOKBACK_DAYS",
        default_lookback=DEFAULT_LOOKBACK_DAYS,
        dry_run_help="Query ClickHouse only; do not export to Dash0",
        fetch_failed="clickhouse spend query failed",
        fetch=get_daily_costs,
        format_row=_format_row,
        attributes=llm_cost_attributes,
        gauges=LLM_COST_GAUGES,
        service_name=SERVICE_NAME,
        log=log,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
