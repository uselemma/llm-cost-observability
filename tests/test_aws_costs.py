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
