from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.cost_export import CostWindowError, build_gauge_specs
from app.export_llm_costs import LLM_COST_GAUGES, llm_cost_attributes
from app.llm_costs import LlmCostError, LlmCostRow, get_daily_costs


class DailyCostQueryTests(unittest.TestCase):
    def _run_query(self) -> tuple[str, dict]:
        captured: dict[str, object] = {}

        def fake_query(sql: str, parameters=None):
            captured["sql"] = sql
            captured["parameters"] = parameters
            return SimpleNamespace(result_rows=[])

        client = SimpleNamespace(query=fake_query)
        with patch("app.llm_costs.get_client", return_value=client):
            get_daily_costs(since="2026-07-01", until="2026-07-02")
        return captured["sql"], captured["parameters"]

    def test_raw_span_scan_is_bounded_and_widened_for_reconciliation(self) -> None:
        sql, params = self._run_query()
        self.assertIn("Timestamp >= subtractMinutes({start:DateTime}, 2)", sql)
        self.assertIn("Timestamp < addMinutes({end:DateTime}, 2)", sql)
        self.assertEqual(params["start"].isoformat(), "2026-07-01T00:00:00")
        self.assertEqual(params["end"].isoformat(), "2026-07-03T00:00:00")

    def test_rollup_is_pinned_to_the_logical_call_day(self) -> None:
        sql, _ = self._run_query()
        self.assertIn("FROM logical_calls", sql)
        self.assertIn("WHERE toDate(timestamp) >= toDate({start:DateTime})", sql)
        self.assertIn("AND toDate(timestamp) < toDate({end:DateTime})", sql)
        self.assertIn("GROUP BY day, model_out, provider_out, feature_out", sql)

    def test_clickhouse_failures_surface_as_llm_cost_error(self) -> None:
        def fail(_sql: str, parameters=None):
            raise RuntimeError("connection refused")

        with patch(
            "app.llm_costs.get_client", return_value=SimpleNamespace(query=fail)
        ):
            with self.assertRaises(LlmCostError):
                get_daily_costs(since="2026-07-01", until="2026-07-02")

    def test_until_before_since_is_rejected(self) -> None:
        with self.assertRaises(CostWindowError):
            get_daily_costs(since="2026-08-31", until="2026-08-01")


class GaugeSpecTests(unittest.TestCase):
    def test_both_metrics_share_one_attribute_set_per_row(self) -> None:
        row = LlmCostRow(
            date="2026-08-01",
            model="claude-sonnet-4",
            provider="anthropic",
            feature="issue",
            spend_usd=1.25,
            calls=4,
        )
        specs = build_gauge_specs([row], LLM_COST_GAUGES, llm_cost_attributes)
        self.assertEqual(
            [spec.name for spec in specs], ["llm.cost.estimated", "llm.calls"]
        )

        expected_attributes = {
            "llm.cost.date": "2026-08-01",
            "gen_ai.request.model": "claude-sonnet-4",
            "gen_ai.provider.name": "anthropic",
            "feature": "issue",
        }
        self.assertEqual(specs[0].points, [(1.25, expected_attributes)])
        self.assertEqual(specs[1].points, [(4.0, expected_attributes)])


if __name__ == "__main__":
    unittest.main()
