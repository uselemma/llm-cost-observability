from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.cost_export import CostWindowError
from app.aws_costs import AwsCostError, AwsCostRow, get_daily_costs, list_accounts
from app.export_aws_costs import publish_aws_cost_gauges


def _ce_page(day: str, groups: list[tuple[str, str]], token: str | None = None) -> dict:
    page = {
        "ResultsByTime": [
            {
                "TimePeriod": {"Start": day, "End": day},
                "Groups": [
                    {"Keys": [service], "Metrics": {"UnblendedCost": {"Amount": amount}}}
                    for service, amount in groups
                ],
            }
        ]
    }
    if token:
        page["NextPageToken"] = token
    return page


class FakeSts:
    def __init__(self, account_id: str) -> None:
        self.account_id = account_id
        self.assumed: list[dict] = []

    def get_caller_identity(self) -> dict[str, str]:
        return {"Account": self.account_id}

    def assume_role(self, **kwargs):
        self.assumed.append(kwargs)
        return {
            "Credentials": {
                "AccessKeyId": "AKIAFAKE",
                "SecretAccessKey": "secret",
                "SessionToken": "token",
            }
        }


class FakeCostExplorer:
    def __init__(self, pages: list[dict]) -> None:
        self.pages = pages
        self.requests: list[dict] = []

    def get_cost_and_usage(self, **kwargs):
        self.requests.append(kwargs)
        return self.pages[len(self.requests) - 1]


class FakeSession:
    def __init__(self, ce: FakeCostExplorer, account_id: str = "806880857007") -> None:
        self.ce = ce
        self.sts = FakeSts(account_id)

    def client(self, name: str, region_name: str | None = None):
        if name == "sts":
            return self.sts
        assert name == "ce"
        assert region_name == "us-east-1"
        return self.ce


class ListAccountsTests(unittest.TestCase):
    def test_parses_name_and_account_id_pairs(self) -> None:
        with patch.dict(os.environ, {"AWS_COST_ACCOUNTS": "prod:1, dev:2"}, clear=False):
            accounts = list_accounts()
        self.assertEqual(
            [(a.name, a.account_id, a.role_arn) for a in accounts],
            [("prod", "1", None), ("dev", "2", None)],
        )

    def test_assume_role_is_attached_by_account_name_not_hardcoded_dev(self) -> None:
        env = {
            "AWS_COST_ACCOUNTS": "prod:1,sandbox:9",
            "AWS_COST_ASSUME_ROLES": "sandbox=arn:aws:iam::9:role/cost",
        }
        with patch.dict(os.environ, env, clear=False):
            accounts = list_accounts()
        self.assertEqual(accounts[0].role_arn, None)
        self.assertEqual(accounts[1].role_arn, "arn:aws:iam::9:role/cost")

    def test_entry_without_account_id_is_rejected(self) -> None:
        with patch.dict(os.environ, {"AWS_COST_ACCOUNTS": "prod"}, clear=False):
            with self.assertRaises(AwsCostError):
                list_accounts()

    def test_empty_value_is_rejected(self) -> None:
        with patch.dict(os.environ, {"AWS_COST_ACCOUNTS": " , "}, clear=False):
            with self.assertRaises(AwsCostError):
                list_accounts()


class GetDailyCostsTests(unittest.TestCase):
    def _run(
        self,
        pages: list[dict],
        *,
        env: dict[str, str] | None = None,
        account_id: str = "806880857007",
    ) -> tuple[object, FakeCostExplorer]:
        ce = FakeCostExplorer(pages)
        merged = {"AWS_COST_ACCOUNTS": "prod:806880857007", **(env or {})}
        with patch.dict(os.environ, merged, clear=False):
            with patch("app.aws_costs.boto3") as boto3_module:
                boto3_module.Session.return_value = FakeSession(ce, account_id)
                payload = get_daily_costs(since="2026-08-01", until="2026-08-01")
        return payload, ce

    def test_requests_daily_unblended_cost_grouped_by_service(self) -> None:
        _, ce = self._run([_ce_page("2026-08-01", [("AmazonEC2", "1.5")])])
        request = ce.requests[0]
        self.assertEqual(request["Granularity"], "DAILY")
        self.assertEqual(request["Metrics"], ["UnblendedCost"])
        self.assertEqual(request["GroupBy"], [{"Type": "DIMENSION", "Key": "SERVICE"}])
        self.assertEqual(
            request["TimePeriod"], {"Start": "2026-08-01", "End": "2026-08-02"}
        )

    def test_paginates_until_the_token_is_exhausted(self) -> None:
        payload, ce = self._run(
            [
                _ce_page("2026-08-01", [("AmazonEC2", "1.5")], token="next"),
                _ce_page("2026-08-01", [("AmazonS3", "2.5")]),
            ]
        )
        self.assertEqual(len(ce.requests), 2)
        self.assertEqual(ce.requests[1]["NextPageToken"], "next")
        self.assertEqual([row.service for row in payload.rows], ["AmazonEC2", "AmazonS3"])

    def test_zero_cost_services_are_dropped(self) -> None:
        payload, _ = self._run(
            [_ce_page("2026-08-01", [("AmazonEC2", "0"), ("AmazonS3", "2.5")])]
        )
        self.assertEqual([row.service for row in payload.rows], ["AmazonS3"])

    def test_wrong_account_credentials_are_reported_not_raised(self) -> None:
        ce = FakeCostExplorer([_ce_page("2026-08-01", [("AmazonEC2", "1.5")])])
        env = {"AWS_COST_ACCOUNTS": "prod:1,dev:2"}
        with patch.dict(os.environ, env, clear=False):
            with patch("app.aws_costs.boto3") as boto3_module:
                boto3_module.Session.return_value = FakeSession(ce, "1")
                payload = get_daily_costs(since="2026-08-01", until="2026-08-01")

        self.assertEqual(len(payload.rows), 1)
        self.assertEqual(len(payload.errors), 1)
        self.assertIn("AWS_COST_ASSUME_ROLES", payload.errors[0])
        self.assertIn("not 2", payload.errors[0])

    def test_all_accounts_failing_raises(self) -> None:
        env = {"AWS_COST_ACCOUNTS": "dev:2"}
        with patch.dict(os.environ, env, clear=False):
            with patch("app.aws_costs.boto3") as boto3_module:
                boto3_module.Session.return_value = FakeSession(
                    FakeCostExplorer([]), "806880857007"
                )
                with self.assertRaises(AwsCostError):
                    get_daily_costs(since="2026-08-01", until="2026-08-01")

    def test_assumed_role_session_is_used_for_matching_account(self) -> None:
        ce = FakeCostExplorer([_ce_page("2026-08-01", [("AmazonEC2", "1.5")])])
        sts = FakeSts("121881624000")
        assumed_session = FakeSession(ce, "121881624000")

        def session_factory(**kwargs):
            if kwargs:
                return assumed_session
            return FakeSession(FakeCostExplorer([]), "806880857007")

        env = {
            "AWS_COST_ACCOUNTS": "dev:121881624000",
            "AWS_COST_ASSUME_ROLES": "dev=arn:aws:iam::121881624000:role/cost",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("app.aws_costs.boto3") as boto3_module:
                boto3_module.client.return_value = sts
                boto3_module.Session.side_effect = session_factory
                payload = get_daily_costs(since="2026-08-01", until="2026-08-01")

        self.assertEqual(len(sts.assumed), 1)
        self.assertEqual(
            sts.assumed[0]["RoleArn"], "arn:aws:iam::121881624000:role/cost"
        )
        self.assertEqual([row.account_name for row in payload.rows], ["dev"])

    def test_until_before_since_is_rejected(self) -> None:
        with self.assertRaises(CostWindowError):
            get_daily_costs(since="2026-08-31", until="2026-08-01")


class GaugeSpecTests(unittest.TestCase):
    def test_cost_rows_become_one_gauge_with_account_and_service_attributes(self) -> None:
        row = AwsCostRow(
            date="2026-08-01",
            account_id="806880857007",
            account_name="prod",
            service="AmazonEC2",
            amount_usd=1.5,
        )
        with patch("app.export_aws_costs.publish_gauges") as publish:
            publish_aws_cost_gauges([row])

        specs = publish.call_args.args[0]
        self.assertEqual([spec.name for spec in specs], ["aws.cost.unblended"])
        self.assertEqual(
            publish.call_args.kwargs["default_service_name"], "aws-cost-exporter"
        )
        self.assertEqual(
            specs[0].points,
            [
                (
                    1.5,
                    {
                        "aws.account.id": "806880857007",
                        "aws.account.name": "prod",
                        "aws.service.name": "AmazonEC2",
                        "aws.cost.date": "2026-08-01",
                    },
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
