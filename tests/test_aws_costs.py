from __future__ import annotations

import unittest
from datetime import date
from unittest import mock

from app.aws_costs import (
    AwsAccount,
    AwsCostError,
    list_accounts,
    resolve_range,
)


class ListAccountsTests(unittest.TestCase):
    def test_parses_default(self) -> None:
        accounts = list_accounts({})
        names = {a.name for a in accounts}
        self.assertEqual(names, {"prod", "dev"})

    def test_parses_custom(self) -> None:
        accounts = list_accounts({"AWS_COST_ACCOUNTS": "a:111,b:222"})
        self.assertEqual(
            accounts, [AwsAccount("a", "111"), AwsAccount("b", "222")]
        )

    def test_rejects_malformed_entry(self) -> None:
        with self.assertRaises(AwsCostError):
            list_accounts({"AWS_COST_ACCOUNTS": "no-colon-here"})

    def test_rejects_empty(self) -> None:
        with self.assertRaises(AwsCostError):
            list_accounts({"AWS_COST_ACCOUNTS": ""})


class ResolveRangeTests(unittest.TestCase):
    def test_explicit_since_until_inclusive(self) -> None:
        start, end = resolve_range("2026-07-01", "2026-08-01", 14)
        self.assertEqual(start, date(2026, 7, 1))
        self.assertEqual(end, date(2026, 8, 2))  # exclusive end = until + 1

    def test_rejects_inverted_range(self) -> None:
        with self.assertRaises(AwsCostError):
            resolve_range("2026-08-02", "2026-08-01", 14)

    def test_rejects_bad_date(self) -> None:
        with self.assertRaises(AwsCostError):
            resolve_range("not-a-date", None, 14)


class GetDailyCostsTests(unittest.TestCase):
    def test_partial_account_failure_still_returns_rows(self) -> None:
        import app.aws_costs as ac

        def fake_fetch(account, start, end, env=None):
            if account.name == "prod":
                return [
                    {
                        "date": "2026-08-13",
                        "account_id": "1",
                        "account_name": "prod",
                        "service": "EC2",
                        "amount_usd": 12.5,
                    }
                ]
            raise ac.AwsCostError("boom")

        with mock.patch.object(ac, "_fetch_account_costs", side_effect=fake_fetch):
            payload = ac.get_daily_costs(
                since="2026-08-13",
                until="2026-08-13",
                env={"AWS_COST_ACCOUNTS": "prod:1,dev:2"},
            )
        self.assertEqual(len(payload["rows"]), 1)
        self.assertEqual(len(payload["errors"]), 1)
        self.assertIn("dev", payload["errors"][0])

    def test_all_accounts_failing_raises(self) -> None:
        import app.aws_costs as ac

        with mock.patch.object(
            ac, "_fetch_account_costs", side_effect=ac.AwsCostError("boom")
        ):
            with self.assertRaises(ac.AwsCostError):
                ac.get_daily_costs(
                    since="2026-08-13",
                    until="2026-08-13",
                    env={"AWS_COST_ACCOUNTS": "prod:1"},
                )


if __name__ == "__main__":
    unittest.main()


class ExcludedRecordTypesTests(unittest.TestCase):
    def test_defaults_to_credit_and_refund(self) -> None:
        from app.aws_costs import excluded_record_types

        self.assertEqual(excluded_record_types({}), ["Credit", "Refund"])

    def test_can_be_overridden(self) -> None:
        from app.aws_costs import excluded_record_types

        self.assertEqual(
            excluded_record_types({"AWS_COST_EXCLUDE_RECORD_TYPES": "Credit, Tax"}),
            ["Credit", "Tax"],
        )

    def test_can_be_disabled(self) -> None:
        from app.aws_costs import excluded_record_types

        self.assertEqual(
            excluded_record_types({"AWS_COST_EXCLUDE_RECORD_TYPES": "none"}), []
        )

    def test_savings_plan_negation_is_not_excluded_by_default(self) -> None:
        """It is the negative half of a matched pair; dropping it double-counts."""
        from app.aws_costs import excluded_record_types

        self.assertNotIn("SavingsPlanNegation", excluded_record_types({}))


class RecordTypeFilterTests(unittest.TestCase):
    """The CE request must carry the RECORD_TYPE filter, not post-filter rows."""

    def _capture_request(self, env: dict[str, str]) -> dict:
        import app.aws_costs as ac

        captured: dict = {}

        class FakeCE:
            def get_cost_and_usage(self, **kwargs):
                captured.update(kwargs)
                return {"ResultsByTime": []}

        class FakeSession:
            def client(self, *args, **kwargs):
                return FakeCE()

        with mock.patch.object(ac, "_session_for_account", return_value=FakeSession()):
            ac._fetch_account_costs(
                AwsAccount("prod", "1"), date(2026, 8, 1), date(2026, 8, 15), env
            )
        return captured

    def test_filter_excludes_credits_by_default(self) -> None:
        request = self._capture_request({})
        self.assertEqual(
            request["Filter"],
            {"Not": {"Dimensions": {"Key": "RECORD_TYPE", "Values": ["Credit", "Refund"]}}},
        )

    def test_no_filter_when_disabled(self) -> None:
        request = self._capture_request({"AWS_COST_EXCLUDE_RECORD_TYPES": "none"})
        self.assertNotIn("Filter", request)

    def test_grouping_and_metric_are_unchanged(self) -> None:
        request = self._capture_request({})
        self.assertEqual(request["Metrics"], ["UnblendedCost"])
        self.assertEqual(request["GroupBy"], [{"Type": "DIMENSION", "Key": "SERVICE"}])
        self.assertEqual(request["Granularity"], "DAILY")
