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

from app.aws_costs import AwsCostRow, get_daily_costs
from app.cost_export import DEFAULT_LOOKBACK_DAYS, GaugeBinding, run_export

METRIC = "aws.cost.unblended"
SERVICE_NAME = "aws-cost-exporter"
log = logging.getLogger("export_aws_costs")


def aws_cost_attributes(row: AwsCostRow) -> dict[str, str]:
    return {
        "aws.account.id": row.account_id,
        "aws.account.name": row.account_name,
        "aws.service.name": row.service,
        "aws.cost.date": row.date,
    }


def _format_row(row: AwsCostRow) -> str:
    return f"dry-run {row.date} {row.account_name} {row.service} ${row.amount_usd:.4f}"


AWS_COST_GAUGES: tuple[GaugeBinding[AwsCostRow], ...] = (
    GaugeBinding(
        name=METRIC,
        unit="USD",
        description="AWS daily UnblendedCost by service and account",
        value=lambda row: row.amount_usd,
    ),
)


def main(argv: list[str] | None = None) -> int:
    return run_export(
        argv,
        description=__doc__,
        lookback_env="AWS_COST_LOOKBACK_DAYS",
        default_lookback=DEFAULT_LOOKBACK_DAYS,
        dry_run_help="Fetch CE only; do not export to Dash0",
        fetch_failed="cost explorer failed",
        fetch=get_daily_costs,
        format_row=_format_row,
        attributes=aws_cost_attributes,
        gauges=AWS_COST_GAUGES,
        service_name=SERVICE_NAME,
        log=log,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
