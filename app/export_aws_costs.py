"""CLI: fetch AWS Cost Explorer daily spend and publish gauges to Dash0.

Publishes one gauge per (day, account, service) row of Cost Explorer's daily
UnblendedCost:

  aws.cost.unblended  — daily USD spend

Attribute keys (PromQL label names use underscores): aws.account.id,
aws.account.name, aws.service.name, aws.cost.date. Each run re-publishes a
rolling lookback window; identical attribute sets update in place, so chart with
last_over_time (same pattern as llm.cost.estimated).

Usage:
  python -m app.export_aws_costs
  python -m app.export_aws_costs --dry-run --lookback-days 3
  python -m app.export_aws_costs --since 2026-07-01 --until 2026-08-01

Env: AWS_COST_ACCOUNTS, AWS_COST_ASSUME_ROLES, AWS_COST_LOOKBACK_DAYS,
DASH0_* (see app.dash0_export), OTEL_SERVICE_NAME (default aws-cost-exporter).
"""
from __future__ import annotations

import logging
import sys
from collections.abc import Sequence

from app.aws_costs import DEFAULT_LOOKBACK_DAYS, AwsCostRow, get_daily_costs
from app.cost_export import run_export
from app.dash0_export import GaugeSpec, PublishResult, publish_gauges

METRIC = "aws.cost.unblended"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("export_aws_costs")


def publish_aws_cost_gauges(rows: Sequence[AwsCostRow]) -> PublishResult:
    spec = GaugeSpec(
        name=METRIC,
        unit="USD",
        description="AWS daily UnblendedCost by service and account",
        points=[row.gauge_point() for row in rows],
    )
    return publish_gauges([spec], default_service_name="aws-cost-exporter")


def main(argv: list[str] | None = None) -> int:
    return run_export(
        argv,
        description=__doc__,
        lookback_env="AWS_COST_LOOKBACK_DAYS",
        default_lookback=DEFAULT_LOOKBACK_DAYS,
        dry_run_help="Fetch CE only; do not export to Dash0",
        fetch_failed="cost explorer failed",
        fetch=get_daily_costs,
        format_row=lambda row: (
            f"dry-run {row.date} {row.account_name} {row.service} ${row.amount_usd:.4f}"
        ),
        publish=publish_aws_cost_gauges,
        published_label=METRIC,
        log=log,
    )


if __name__ == "__main__":
    sys.exit(main())
