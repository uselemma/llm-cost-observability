from __future__ import annotations

import unittest
from datetime import date
from unittest import mock

from app.vendors import vercel
from app.vendors.base import VendorCostError

CREDS = {"VERCEL_BILLING_TOKEN": "tok", "VERCEL_TEAM_ID": "team_1"}


def _charge(**overrides) -> dict:
    record = {
        "ChargePeriodStart": "2026-08-13T00:00:00Z",
        "ChargePeriodEnd": "2026-08-14T00:00:00Z",
        "ChargeCategory": "Usage",
        "ServiceName": "Edge Requests",
        "BilledCost": 1.5,
        "BillingCurrency": "USD",
    }
    record.update(overrides)
    return record


class ConfigTests(unittest.TestCase):
    def test_needs_token_and_team(self) -> None:
        self.assertTrue(vercel.is_configured(CREDS))
        self.assertFalse(vercel.is_configured({"VERCEL_BILLING_TOKEN": "tok"}))

    def test_default_excludes_ai_gateway(self) -> None:
        self.assertEqual(vercel.excluded_services({}), ("ai gateway",))

    def test_exclusion_can_be_disabled(self) -> None:
        self.assertEqual(
            vercel.excluded_services({"VERCEL_EXCLUDE_SERVICES": "none"}), ()
        )

    def test_exclusion_list_is_configurable(self) -> None:
        self.assertEqual(
            vercel.excluded_services({"VERCEL_EXCLUDE_SERVICES": "AI Gateway, Blob"}),
            ("ai gateway", "blob"),
        )


class FetchTests(unittest.TestCase):
    def _fetch(self, records, env=None):
        with mock.patch.object(vercel, "get_jsonl", return_value=iter(records)):
            return vercel.fetch(date(2026, 8, 13), date(2026, 8, 14), env or CREDS)

    def test_maps_focus_record(self) -> None:
        rows = self._fetch([_charge()])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].provider, "vercel")
        self.assertEqual(rows[0].service, "Edge Requests")
        self.assertEqual(rows[0].date, "2026-08-13")
        self.assertEqual(rows[0].cost_usd, 1.5)

    def test_ai_gateway_excluded_to_avoid_double_counting_llm_spend(self) -> None:
        rows = self._fetch(
            [_charge(ServiceName="AI Gateway", BilledCost=99.0), _charge()]
        )
        self.assertEqual([row.service for row in rows], ["Edge Requests"])

    def test_ai_gateway_included_when_exclusion_disabled(self) -> None:
        env = dict(CREDS, VERCEL_EXCLUDE_SERVICES="none")
        rows = self._fetch([_charge(ServiceName="AI Gateway", BilledCost=99.0)], env)
        self.assertEqual(len(rows), 1)

    def test_credits_are_kept_purchases_are_not(self) -> None:
        rows = self._fetch(
            [
                _charge(ChargeCategory="Credit", BilledCost=-5.0),
                _charge(ChargeCategory="Purchase", BilledCost=1000.0),
            ]
        )
        self.assertEqual([row.cost_usd for row in rows], [-5.0])

    def test_zero_cost_rows_dropped(self) -> None:
        self.assertEqual(self._fetch([_charge(BilledCost=0)]), [])

    def test_missing_credentials_raise(self) -> None:
        with self.assertRaises(VendorCostError):
            vercel.fetch(date(2026, 8, 13), date(2026, 8, 14), {})

    def test_request_uses_exclusive_end(self) -> None:
        captured: dict[str, str] = {}

        def fake_get_jsonl(url, headers, timeout=60):
            captured["url"] = url
            return iter(())

        with mock.patch.object(vercel, "get_jsonl", side_effect=fake_get_jsonl):
            vercel.fetch(date(2026, 8, 1), date(2026, 8, 15), CREDS)

        self.assertIn("from=2026-08-01T00%3A00%3A00%2B00%3A00", captured["url"])
        self.assertIn("to=2026-08-15T00%3A00%3A00%2B00%3A00", captured["url"])


if __name__ == "__main__":
    unittest.main()
