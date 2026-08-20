from __future__ import annotations

import unittest
from datetime import date

from app.vendors.base import (
    ENV_PROD,
    SOURCE_METERED,
    CostRow,
    VendorCostError,
    resolve_range,
)


class ResolveRangeTests(unittest.TestCase):
    def test_explicit_range_is_inclusive_of_until(self) -> None:
        start, end = resolve_range("2026-07-01", "2026-07-14", 14)
        self.assertEqual(start, date(2026, 7, 1))
        self.assertEqual(end, date(2026, 7, 15))

    def test_lookback_window_length(self) -> None:
        start, end = resolve_range(None, None, 14)
        self.assertEqual((end - start).days, 14)

    def test_rejects_inverted_range(self) -> None:
        with self.assertRaises(VendorCostError):
            resolve_range("2026-08-02", "2026-08-01", 14)

    def test_rejects_bad_date(self) -> None:
        with self.assertRaises(VendorCostError):
            resolve_range("yesterday", None, 14)


class CostRowTests(unittest.TestCase):
    def test_attribute_keys_match_promql_labels(self) -> None:
        row = CostRow(
            date="2026-08-13",
            provider="aws",
            service="Amazon EKS",
            cost_usd=1.25,
            source=SOURCE_METERED,
            env=ENV_PROD,
        )
        self.assertEqual(
            row.attributes(),
            {
                "saas.cost.date": "2026-08-13",
                "saas.provider": "aws",
                "saas.service": "Amazon EKS",
                "saas.cost.source": "metered",
                "saas.env": "prod",
            },
        )


if __name__ == "__main__":
    unittest.main()
