from __future__ import annotations

import unittest
from datetime import date
from unittest import mock

from app.vendors import cloudflare
from app.vendors.base import VendorCostError

CREDS = {"CF_BILLING_TOKEN": "tok", "CF_ACCOUNT_ID": "acct"}


def _charge(**overrides) -> dict:
    record = {
        "ChargePeriodStart": "2026-08-13T00:00:00Z",
        "ServiceName": "Workers Standard",
        "ServiceFamilyName": "Workers",
        "ContractedCost": 2.0,
        "BillingCurrency": "USD",
    }
    record.update(overrides)
    return record


class FetchTests(unittest.TestCase):
    def _fetch(self, records, start=date(2026, 8, 13), end=date(2026, 8, 14)):
        payload = {"result": records}
        with mock.patch.object(cloudflare, "get_json", return_value=payload):
            return cloudflare.fetch_with_coverage(start, end, CREDS)

    def test_maps_and_qualifies_service_with_family(self) -> None:
        rows, warning = self._fetch([_charge()])
        self.assertEqual(rows[0].service, "Workers / Workers Standard")
        self.assertEqual(rows[0].cost_usd, 2.0)
        self.assertEqual(warning, "")

    def test_family_not_repeated_when_same_as_name(self) -> None:
        rows, _ = self._fetch([_charge(ServiceName="R2", ServiceFamilyName="R2")])
        self.assertEqual(rows[0].service, "R2")

    def test_falls_back_through_cost_fields(self) -> None:
        record = _charge()
        record.pop("ContractedCost")
        record["BilledCost"] = 7.0
        rows, _ = self._fetch([record])
        self.assertEqual(rows[0].cost_usd, 7.0)

    def test_rows_outside_window_are_filtered(self) -> None:
        rows, _ = self._fetch(
            [_charge(ChargePeriodStart="2026-08-20T00:00:00Z"), _charge()]
        )
        self.assertEqual([row.date for row in rows], ["2026-08-13"])

    def test_partial_billing_period_is_reported(self) -> None:
        rows, warning = self._fetch(
            [_charge(ChargePeriodStart="2026-08-10T00:00:00Z")],
            start=date(2026, 8, 1),
            end=date(2026, 8, 15),
        )
        self.assertEqual(len(rows), 1)
        self.assertIn("2026-08-10", warning)
        self.assertIn("cycle anchor", warning)

    def test_non_usd_currency_raises_rather_than_mixing_units(self) -> None:
        with self.assertRaises(VendorCostError):
            self._fetch([_charge(BillingCurrency="EUR")])

    def test_missing_credentials_raise(self) -> None:
        with self.assertRaises(VendorCostError):
            cloudflare.fetch(date(2026, 8, 13), date(2026, 8, 14), {})


if __name__ == "__main__":
    unittest.main()
