"""AWS Cost Explorer helpers for daily spend by service/account.

Reports the cost of actually running the workload: promotional credits and
refunds are filtered out (see DEFAULT_EXCLUDED_RECORD_TYPES), so the figure is
what the usage would cost at list price rather than what happened to be
invoiced after credits.

Auth is the default credential chain (IRSA in-cluster, AWS_PROFILE locally).
The configured "dev" account is queried via sts:AssumeRole into
AWS_COST_DEV_ROLE_ARN from the prod principal. Cost Explorer is always called
in us-east-1 regardless of the account's home region.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

CE_REGION = "us-east-1"
DEFAULT_ACCOUNTS = "prod:806880857007,dev:121881624000"
DEFAULT_LOOKBACK_DAYS = 14

# Cost Explorer returns every RECORD_TYPE by default, so promotional credits
# and refunds come back as negative UnblendedCost line items that cancel the
# positive usage they offset. On a credit-covered account that nets the whole
# bill to ~$0, which makes "cost per trace" read as free while real resources
# are being consumed -- and it silently stops being true the day the credits
# run out. We want the cost of actually serving traffic, so credits are
# excluded and the figure is what we would pay at list.
#
# Only Credit and Refund are dropped. Negative record types that are one half
# of a matched pair -- SavingsPlanNegation against SavingsPlanCoveredUsage,
# for instance -- must stay, or the surviving half double-counts.
DEFAULT_EXCLUDED_RECORD_TYPES = "Credit,Refund"


@dataclass(frozen=True)
class AwsAccount:
    name: str
    account_id: str


class AwsCostError(Exception):
    """Raised when Cost Explorer cannot be queried."""


def list_accounts(env: dict[str, str] | None = None) -> list[AwsAccount]:
    e = env if env is not None else os.environ
    raw = e.get("AWS_COST_ACCOUNTS", DEFAULT_ACCOUNTS).strip()
    accounts: list[AwsAccount] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        name, _, account_id = part.partition(":")
        name = name.strip()
        account_id = account_id.strip()
        if not name or not account_id:
            raise AwsCostError(
                f"invalid AWS_COST_ACCOUNTS entry {part!r}; expected name:account_id"
            )
        accounts.append(AwsAccount(name=name, account_id=account_id))
    if not accounts:
        raise AwsCostError("AWS_COST_ACCOUNTS is empty")
    return accounts


def excluded_record_types(env: dict[str, str] | None = None) -> list[str]:
    """RECORD_TYPE values to drop from Cost Explorer results.

    Set AWS_COST_EXCLUDE_RECORD_TYPES to override; "none" keeps everything
    (the old credit-netted behaviour).
    """
    e = env if env is not None else os.environ
    raw = e.get("AWS_COST_EXCLUDE_RECORD_TYPES", DEFAULT_EXCLUDED_RECORD_TYPES)
    raw = raw.strip()
    if not raw or raw.lower() in ("-", "none", "off"):
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _parse_day(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError as exc:
        raise AwsCostError(f"invalid {field} date, expected YYYY-MM-DD") from exc


def resolve_range(
    since: str | None, until: str | None, lookback_days: int
) -> tuple[date, date]:
    """Return (inclusive start day, exclusive end day)."""
    default_end = date.today() + timedelta(days=1)
    start = (
        _parse_day(since, "since")
        if since
        else default_end - timedelta(days=max(1, lookback_days))
    )
    end = _parse_day(until, "until") + timedelta(days=1) if until else default_end
    if end <= start:
        raise AwsCostError("until must be on or after since")
    return start, end


def _session_for_account(
    account: AwsAccount, env: dict[str, str] | None = None
) -> boto3.Session:
    e = env if env is not None else os.environ
    if account.name == "dev":
        role_arn = e.get("AWS_COST_DEV_ROLE_ARN", "").strip()
        if not role_arn:
            raise AwsCostError(
                "AWS_COST_DEV_ROLE_ARN is required to query the dev account"
            )
        sts = boto3.client("sts")
        assumed = sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName="aig-observability-cost",
            DurationSeconds=3600,
        )
        creds = assumed["Credentials"]
        return boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        )
    return boto3.Session()


def _fetch_account_costs(
    account: AwsAccount,
    start: date,
    end: date,
    env: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    session = _session_for_account(account, env)
    ce = session.client("ce", region_name=CE_REGION)
    rows: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {
            "TimePeriod": {"Start": start.isoformat(), "End": end.isoformat()},
            "Granularity": "DAILY",
            "Metrics": ["UnblendedCost"],
            "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
        }
        excluded = excluded_record_types(env)
        if excluded:
            kwargs["Filter"] = {
                "Not": {"Dimensions": {"Key": "RECORD_TYPE", "Values": excluded}}
            }
        if token:
            kwargs["NextPageToken"] = token
        response = ce.get_cost_and_usage(**kwargs)
        for day in response.get("ResultsByTime", []):
            day_start = day["TimePeriod"]["Start"]
            for group in day.get("Groups", []):
                keys = group.get("Keys") or []
                service = keys[0] if keys else "Unknown"
                amount = float(
                    group.get("Metrics", {})
                    .get("UnblendedCost", {})
                    .get("Amount", "0")
                    or 0
                )
                if amount == 0:
                    continue
                rows.append(
                    {
                        "date": day_start,
                        "account_id": account.account_id,
                        "account_name": account.name,
                        "service": service,
                        "amount_usd": amount,
                    }
                )
        token = response.get("NextPageToken")
        if not token:
            break
    return rows


def get_daily_costs(
    since: str | None = None,
    until: str | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return daily UnblendedCost by service for every configured account.

    Never raises for a single account's failure — partial results are
    returned with per-account errors listed, so one broken assume-role
    doesn't block publishing the accounts that did work.
    """
    start, end = resolve_range(since, until, lookback_days)
    accounts = list_accounts(env)

    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for account in accounts:
        try:
            rows.extend(_fetch_account_costs(account, start, end, env))
        except (AwsCostError, BotoCoreError, ClientError) as exc:
            errors.append(f"{account.name}: {exc}")

    if not rows and errors:
        raise AwsCostError("; ".join(errors))

    rows.sort(key=lambda r: (r["date"], r["account_name"], r["service"]))
    return {
        "rows": rows,
        "since": start.isoformat(),
        "until": (end - timedelta(days=1)).isoformat(),
        "errors": errors,
    }
