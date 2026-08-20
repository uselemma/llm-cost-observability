from __future__ import annotations

import unittest
from datetime import date
from unittest import mock

from app.vendors import clickhouse_cloud as chc
from app.vendors.base import VendorCostError

CREDS = {
    "CLICKHOUSE_CLOUD_ORG_ID": "org-1",
    "CLICKHOUSE_CLOUD_KEY_ID": "key",
    "CLICKHOUSE_CLOUD_KEY_SECRET": "secret",
}


class ConfigTests(unittest.TestCase):
    def test_requires_all_three_keys(self) -> None:
        self.assertTrue(chc.is_configured(CREDS))
        partial = dict(CREDS)
        partial.pop("CLICKHOUSE_CLOUD_KEY_SECRET")
        self.assertFalse(chc.is_configured(partial))

    def test_rejects_non_numeric_chc_rate(self) -> None:
        with self.assertRaises(VendorCostError):
            chc._chc_usd({"CLICKHOUSE_CLOUD_CHC_USD": "one dollar"})


class WindowTests(unittest.TestCase):
    def test_splits_beyond_api_cap(self) -> None:
        windows = chc._windows(date(2026, 1, 1), date(2026, 3, 1))
        self.assertEqual(len(windows), 2)
        self.assertEqual(windows[0], (date(2026, 1, 1), date(2026, 1, 30)))
        # No gap and no overlap between chunks.
        self.assertEqual(windows[1][0], date(2026, 1, 31))
        self.assertEqual(windows[-1][1], date(2026, 2, 28))

    def test_single_window_within_cap(self) -> None:
        windows = chc._windows(date(2026, 8, 1), date(2026, 8, 15))
        self.assertEqual(windows, [(date(2026, 8, 1), date(2026, 8, 14))])


class RecordMappingTests(unittest.TestCase):
    def test_splits_metrics_into_services(self) -> None:
        rows = chc._rows_from_record(
            {
                "date": "2026-08-13",
                "entityType": "service",
                "entityName": "aig",
                "totalCHC": 3.0,
                "metrics": {"computeCHC": 2.0, "publicDataTransferCHC": 1.0},
            },
            chc_usd=1.0,
        )
        services = {row.service: row.cost_usd for row in rows}
        self.assertEqual(services["Compute (aig)"], 2.0)
        self.assertEqual(services["Public data transfer (aig)"], 1.0)
        self.assertNotIn("Other (aig)", services)

    def test_unmapped_remainder_is_published_not_dropped(self) -> None:
        rows = chc._rows_from_record(
            {
                "date": "2026-08-13",
                "entityName": "wh",
                "totalCHC": 5.0,
                "metrics": {"computeCHC": 2.0, "someNewCHC": 3.0},
            },
            chc_usd=1.0,
        )
        services = {row.service: row.cost_usd for row in rows}
        self.assertEqual(services["Other (wh)"], 3.0)
        self.assertAlmostEqual(sum(services.values()), 5.0)

    def test_applies_chc_conversion(self) -> None:
        rows = chc._rows_from_record(
            {
                "date": "2026-08-13",
                "entityName": "aig",
                "totalCHC": 2.0,
                "metrics": {"computeCHC": 2.0},
            },
            chc_usd=0.9,
        )
        self.assertAlmostEqual(rows[0].cost_usd, 1.8)


class FetchTests(unittest.TestCase):
    def test_builds_expected_request_and_maps_rows(self) -> None:
        captured: dict[str, object] = {}

        def fake_get_json(url, headers, timeout=60):
            captured["url"] = url
            captured["headers"] = headers
            return {
                "result": {
                    "grandTotalCHC": 4.0,
                    "costs": [
                        {
                            "date": "2026-08-13",
                            "entityName": "aig",
                            "totalCHC": 4.0,
                            "metrics": {"computeCHC": 4.0},
                        }
                    ],
                }
            }

        with mock.patch.object(chc, "get_json", side_effect=fake_get_json):
            rows = chc.fetch(date(2026, 8, 13), date(2026, 8, 14), CREDS)

        self.assertIn("/v1/organizations/org-1/usageCost", str(captured["url"]))
        self.assertIn("from_date=2026-08-13", str(captured["url"]))
        self.assertIn("to_date=2026-08-13", str(captured["url"]))
        self.assertTrue(
            str(captured["headers"]["Authorization"]).startswith("Basic ")
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].provider, "clickhouse_cloud")
        self.assertEqual(rows[0].cost_usd, 4.0)

    def test_missing_credentials_raise(self) -> None:
        with self.assertRaises(VendorCostError):
            chc.fetch(date(2026, 8, 13), date(2026, 8, 14), {})


if __name__ == "__main__":
    unittest.main()
