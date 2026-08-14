"""AWS Cost Explorer helpers for daily spend by service/account.

Auth is the default credential chain (IRSA in prod, AWS_PROFILE locally).
Accounts listed in AWS_COST_ASSUME_ROLES are queried via sts:AssumeRole.
Cost Explorer is always called in us-east-1.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.cost_export import (
    DEFAULT_LOOKBACK_DAYS,
    CostExportError,
    CostReport,
    resolve_range,
)

CE_REGION = "us-east-1"
DEFAULT_ACCOUNTS = "prod:806880857007,dev:121881624000"

_CE_QUERY = {
    "Granularity": "DAILY",
    "Metrics": ["UnblendedCost"],
    "GroupBy": [{"Type": "DIMENSION", "Key": "SERVICE"}],
}


@dataclass(frozen=True)
class AwsAccount:
    name: str
    account_id: str
    role_arn: str | None = None


@dataclass(frozen=True)
class AwsCostRow:
    date: str
    account_id: str
    account_name: str
    service: str
    amount_usd: float


class AwsCostError(CostExportError):
    """Raised when Cost Explorer cannot be queried."""


def _pairs(raw: str, separator: str, *, env: str, expected: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        name, sep, value = part.partition(separator)
        name, value = name.strip(), value.strip()
        if not sep or not name or not value:
            raise AwsCostError(f"invalid {env} entry {part!r}; expected {expected}")
        pairs.append((name, value))
    return pairs


def list_accounts() -> list[AwsAccount]:
    raw = os.environ.get("AWS_COST_ACCOUNTS", DEFAULT_ACCOUNTS).strip()
    roles = dict(
        _pairs(
            os.environ.get("AWS_COST_ASSUME_ROLES", "").strip(),
            "=",
            env="AWS_COST_ASSUME_ROLES",
            expected="name=role_arn",
        )
    )
    accounts = [
        AwsAccount(name=name, account_id=account_id, role_arn=roles.get(name))
        for name, account_id in _pairs(
            raw, ":", env="AWS_COST_ACCOUNTS", expected="name:account_id"
        )
    ]
    if not accounts:
        raise AwsCostError("AWS_COST_ACCOUNTS is empty")
    return accounts


def _session_for_account(account: AwsAccount) -> boto3.Session:
    if not account.role_arn:
        return boto3.Session()
    assumed = boto3.client("sts").assume_role(
        RoleArn=account.role_arn,
        RoleSessionName="aig-observability-cost",
        DurationSeconds=3600,
    )
    creds = assumed["Credentials"]
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )


def _unblended_amount(group: dict) -> float:
    raw = group.get("Metrics", {}).get("UnblendedCost", {}).get("Amount", "0")
    return float(raw or 0)


def _rows_from_page(account: AwsAccount, response: dict) -> list[AwsCostRow]:
    rows: list[AwsCostRow] = []
    for day in response.get("ResultsByTime", []):
        day_start = day["TimePeriod"]["Start"]
        for group in day.get("Groups", []):
            amount = _unblended_amount(group)
            if amount == 0:
                continue
            keys = group.get("Keys") or []
            rows.append(
                AwsCostRow(
                    date=day_start,
                    account_id=account.account_id,
                    account_name=account.name,
                    service=keys[0] if keys else "Unknown",
                    amount_usd=amount,
                )
            )
    return rows


def _fetch_account_costs(
    account: AwsAccount, start: date, end: date
) -> list[AwsCostRow]:
    session = _session_for_account(account)
    caller = session.client("sts").get_caller_identity()["Account"]
    if caller != account.account_id:
        raise AwsCostError(
            f"credentials are for account {caller}, "
            f"not {account.account_id} (set AWS_COST_ASSUME_ROLES)"
        )
    ce = session.client("ce", region_name=CE_REGION)
    rows: list[AwsCostRow] = []
    token: str | None = None
    period = {"Start": start.isoformat(), "End": end.isoformat()}
    while True:
        kwargs = {**_CE_QUERY, "TimePeriod": period}
        if token:
            kwargs["NextPageToken"] = token
        response = ce.get_cost_and_usage(**kwargs)
        rows.extend(_rows_from_page(account, response))
        token = response.get("NextPageToken")
        if not token:
            break
    return rows


def get_daily_costs(
    since: str | None = None,
    until: str | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> CostReport[AwsCostRow]:
    """Return daily UnblendedCost by service for configured accounts."""
    window = resolve_range(since, until, lookback_days)
    accounts = list_accounts()
    rows: list[AwsCostRow] = []
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=max(1, len(accounts))) as pool:
        futs = {
            account: pool.submit(
                _fetch_account_costs, account, window.start, window.end
            )
            for account in accounts
        }
        for account in accounts:
            try:
                rows.extend(futs[account].result())
            except (AwsCostError, BotoCoreError, ClientError) as exc:
                errors.append(f"{account.name}: {exc}")

    if not rows and errors:
        raise AwsCostError("; ".join(errors))

    rows.sort(key=lambda r: (r.date, r.account_name, r.service))
    return CostReport(rows=rows, window=window, errors=tuple(errors))
