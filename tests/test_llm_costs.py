from __future__ import annotations

import unittest
from datetime import date, timedelta
from unittest import mock

import app.llm_costs as lc
from app.llm_costs import LlmCostError, resolve_range


class ResolveRangeTests(unittest.TestCase):
    def test_default_window_includes_partial_today(self) -> None:
        start, end = resolve_range(None, None, 14)
        self.assertEqual(end, date.today() + timedelta(days=1))
        self.assertEqual((end - start).days, 14)

    def test_explicit_since_until_inclusive(self) -> None:
        start, end = resolve_range("2026-07-01", "2026-08-01", 14)
        self.assertEqual(start, date(2026, 7, 1))
        self.assertEqual(end, date(2026, 8, 2))

    def test_rejects_inverted_range(self) -> None:
        with self.assertRaises(LlmCostError):
            resolve_range("2026-08-02", "2026-08-01", 14)


class GetDailyCostsTests(unittest.TestCase):
    def test_builds_query_over_logical_calls_with_widened_bounds(self) -> None:
        class FakeResult:
            result_rows = [
                ("2026-08-13", "claude-sonnet-5", "anthropic", "summarization", 12.5, 340),
                ("2026-08-13", "", "", "", 0.0, 1),
            ]

        class FakeClient:
            def query(self, query: str):
                self.captured_query = query
                return FakeResult()

        fake_client = FakeClient()
        with mock.patch.object(lc, "get_client", return_value=fake_client):
            payload = lc.get_daily_costs(since="2026-08-01", until="2026-08-14")

        query = fake_client.captured_query
        self.assertIn("WITH root_spans AS", query)
        self.assertIn("FROM logical_calls", query)
        self.assertIn(
            "toDateTime('2026-08-01 00:00:00') - INTERVAL 2 MINUTE", query
        )
        self.assertIn(
            "toDateTime('2026-08-15 00:00:00') + INTERVAL 2 MINUTE", query
        )
        self.assertIn("toDate('2026-08-01')", query)
        self.assertIn("toDate('2026-08-15')", query)
        self.assertIn(
            "GROUP BY day, model_out, provider_out, feature_out", query
        )

        self.assertEqual(len(payload["rows"]), 2)
        self.assertEqual(payload["rows"][0]["model"], "claude-sonnet-5")
        self.assertEqual(payload["rows"][0]["spend_usd"], 12.5)
        self.assertEqual(payload["rows"][0]["calls"], 340)
        self.assertEqual(payload["since"], "2026-08-01")
        self.assertEqual(payload["until"], "2026-08-14")

    def test_clickhouse_failure_wraps_as_llm_cost_error(self) -> None:
        class FailingClient:
            def query(self, query: str):
                raise RuntimeError("connection refused")

        with mock.patch.object(lc, "get_client", return_value=FailingClient()):
            with self.assertRaises(LlmCostError):
                lc.get_daily_costs(since="2026-08-01", until="2026-08-02")


if __name__ == "__main__":
    unittest.main()
