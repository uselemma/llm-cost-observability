from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date

from app.vendors import declared
from app.vendors.base import VendorCostError


class RateCardFileTests(unittest.TestCase):
    def _write(self, body: str) -> dict[str, str]:
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".yaml", delete=False, encoding="utf-8"
        )
        handle.write(body)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return {"SAAS_RATE_CARD_PATH": handle.name}

    def test_amortizes_monthly_to_daily(self) -> None:
        env = self._write(
            "vendors:\n"
            "  - provider: dash0\n"
            "    service: Observability\n"
            "    monthly_usd: 365\n"
        )
        rows = declared.fetch(date(2026, 8, 1), date(2026, 8, 8), env)
        self.assertEqual(len(rows), 7)
        self.assertAlmostEqual(rows[0].cost_usd, 365 * 12 / 365.0)
        self.assertEqual(rows[0].source, "declared")
        self.assertEqual(rows[0].provider, "dash0")

    def test_unpriced_entries_are_skipped_not_guessed(self) -> None:
        env = self._write(
            "vendors:\n"
            "  - provider: dash0\n"
            "    service: Observability\n"
            "    monthly_usd: null\n"
            "  - provider: resend\n"
            "    service: Email\n"
            "    monthly_usd: 30\n"
        )
        rows = declared.fetch(date(2026, 8, 1), date(2026, 8, 3), env)
        self.assertEqual({row.provider for row in rows}, {"resend"})
        self.assertEqual(declared.unpriced(env), ["dash0"])

    def test_rejects_missing_provider(self) -> None:
        env = self._write("vendors:\n  - service: Observability\n    monthly_usd: 1\n")
        with self.assertRaises(VendorCostError):
            declared.load_rate_card(env)

    def test_rejects_non_numeric_amount(self) -> None:
        env = self._write(
            "vendors:\n  - provider: a\n    service: b\n    monthly_usd: lots\n"
        )
        with self.assertRaises(VendorCostError):
            declared.load_rate_card(env)

    def test_rejects_negative_amount(self) -> None:
        env = self._write(
            "vendors:\n  - provider: a\n    service: b\n    monthly_usd: -5\n"
        )
        with self.assertRaises(VendorCostError):
            declared.load_rate_card(env)

    def test_rejects_unknown_env(self) -> None:
        env = self._write(
            "vendors:\n"
            "  - provider: a\n    service: b\n    monthly_usd: 5\n    env: staging\n"
        )
        with self.assertRaises(VendorCostError):
            declared.load_rate_card(env)

    def test_missing_file_reports_path(self) -> None:
        with self.assertRaises(VendorCostError):
            declared.load_rate_card({"SAAS_RATE_CARD_PATH": "/nonexistent/rc.yaml"})


class ShippedRateCardTests(unittest.TestCase):
    """The checked-in card must stay loadable even while entries are unpriced."""

    def test_shipped_card_parses(self) -> None:
        entries = declared.load_rate_card({})
        self.assertTrue(entries)
        self.assertTrue(all("provider" in entry for entry in entries))

    def test_shipped_card_publishes_nothing_until_filled_in(self) -> None:
        rows = declared.fetch(date(2026, 8, 1), date(2026, 8, 3), {})
        priced = [
            entry
            for entry in declared.load_rate_card({})
            if entry.get("monthly_usd") is not None
        ]
        self.assertEqual(bool(rows), bool(priced))


if __name__ == "__main__":
    unittest.main()
