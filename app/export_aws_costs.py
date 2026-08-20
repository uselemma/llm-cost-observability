"""CLI: fetch AWS Cost Explorer daily spend and publish gauges to Dash0.

Publishes one gauge per (date, account, service) row:

  aws.cost.unblended  -- AWS daily UnblendedCost, excluding credits/refunds
                         (cost of running the workload, not the net invoice)

Attribute keys (PromQL label names use underscores): aws.cost.date,
aws.account.id, aws.account.name, aws.service.name. Each run re-publishes a
rolling lookback window; identical attribute sets update in place, so chart
with last_over_time.

Usage:
  python -m app.export_aws_costs
  python -m app.export_aws_costs --dry-run --lookback-days 3
  python -m app.export_aws_costs --since 2026-07-01 --until 2026-08-01

Env: AWS_COST_ACCOUNTS, AWS_COST_DEV_ROLE_ARN, AWS_COST_LOOKBACK_DAYS,
DASH0_INGESTION_URL ("off" disables), DASH0_INGESTION_KEY or DASH0_TOKEN,
DASH0_DATASET (default production), OTEL_SERVICE_NAME.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from app.aws_costs import AwsCostError, DEFAULT_LOOKBACK_DAYS, get_daily_costs
from app.dash0_export import GaugeSpec, PublishResult, publish_gauges

METRIC_NAME = "aws.cost.unblended"
SERVICE_NAME = "aws-cost-exporter"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("export_aws_costs")


def publish_aws_cost_gauges(
    rows: list[dict], *, env: dict[str, str] | None = None
) -> PublishResult:
    spec = GaugeSpec(
        name=METRIC_NAME,
        unit="USD",
        description="AWS daily UnblendedCost by service and account",
        points=[
            (
                float(row["amount_usd"]),
                {
                    "aws.account.id": str(row["account_id"]),
                    "aws.account.name": str(row["account_name"]),
                    "aws.service.name": str(row["service"]),
                    "aws.cost.date": str(row["date"]),
                },
            )
            for row in rows
        ],
    )
    return publish_gauges([spec], service_name=SERVICE_NAME, env=env)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", help="Inclusive start date YYYY-MM-DD")
    parser.add_argument("--until", help="Inclusive end date YYYY-MM-DD")
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=int(os.environ.get("AWS_COST_LOOKBACK_DAYS", DEFAULT_LOOKBACK_DAYS)),
        help=f"Days to fetch when --since/--until omitted (default {DEFAULT_LOOKBACK_DAYS})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch Cost Explorer only; do not export to Dash0",
    )
    args = parser.parse_args(argv)

    try:
        payload = get_daily_costs(
            since=args.since, until=args.until, lookback_days=args.lookback_days
        )
    except AwsCostError as exc:
        log.error("cost explorer failed: %s", exc)
        return 1

    rows = payload["rows"]
    log.info(
        "fetched %d rows (%s .. %s); account errors=%s",
        len(rows),
        payload["since"],
        payload["until"],
        payload["errors"] or "none",
    )

    if args.dry_run:
        for row in rows[:20]:
            log.info(
                "dry-run %s %s %s $%.4f",
                row["date"],
                row["account_name"],
                row["service"],
                row["amount_usd"],
            )
        if len(rows) > 20:
            log.info("... %d more rows", len(rows) - 20)
        return 0 if rows or not payload["errors"] else 1

    result = publish_aws_cost_gauges(rows)
    if not result.ok:
        log.error("dash0 export failed: %s", result.reason)
        return 1

    log.info("published %d %s points to Dash0", result.points, METRIC_NAME)
    if payload["errors"]:
        log.warning("partial CE failures: %s", "; ".join(payload["errors"]))
        return 0 if result.points else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
