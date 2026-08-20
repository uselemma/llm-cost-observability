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
    """SQL shape and row mapping, pinned to one chunk.

    LLM_COST_CHUNK_DAYS=14 collapses the window to a single query so these
    assertions describe the generated SQL, not the chunk split -- that is
    covered separately by ChunkedQueryTests.
    """

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
            payload = lc.get_daily_costs(
                since="2026-08-01",
                until="2026-08-14",
                env={"LLM_COST_CHUNK_DAYS": "14"},
            )

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


class ChunkDaysTests(unittest.TestCase):
    def test_defaults_to_one_day(self) -> None:
        from app.llm_costs import chunk_days

        self.assertEqual(chunk_days({}), 1)

    def test_reads_override(self) -> None:
        from app.llm_costs import chunk_days

        self.assertEqual(chunk_days({"LLM_COST_CHUNK_DAYS": "7"}), 7)

    def test_rejects_non_integer(self) -> None:
        from app.llm_costs import LlmCostError, chunk_days

        with self.assertRaises(LlmCostError):
            chunk_days({"LLM_COST_CHUNK_DAYS": "a week"})

    def test_rejects_zero(self) -> None:
        from app.llm_costs import LlmCostError, chunk_days

        with self.assertRaises(LlmCostError):
            chunk_days({"LLM_COST_CHUNK_DAYS": "0"})


class WindowSplitTests(unittest.TestCase):
    def test_one_window_per_day_by_default(self) -> None:
        from app.llm_costs import _windows

        windows = _windows(date(2026, 8, 1), date(2026, 8, 15), 1)
        self.assertEqual(len(windows), 14)
        self.assertEqual(windows[0], (date(2026, 8, 1), date(2026, 8, 2)))
        self.assertEqual(windows[-1], (date(2026, 8, 14), date(2026, 8, 15)))

    def test_windows_are_contiguous_and_cover_exactly(self) -> None:
        from app.llm_costs import _windows

        windows = _windows(date(2026, 8, 1), date(2026, 8, 15), 4)
        self.assertEqual(windows[0][0], date(2026, 8, 1))
        self.assertEqual(windows[-1][1], date(2026, 8, 15))
        for earlier, later in zip(windows, windows[1:]):
            self.assertEqual(earlier[1], later[0])  # no gap, no overlap

    def test_final_window_is_truncated_not_overrun(self) -> None:
        from app.llm_costs import _windows

        windows = _windows(date(2026, 8, 1), date(2026, 8, 10), 4)
        self.assertEqual(windows[-1], (date(2026, 8, 9), date(2026, 8, 10)))


class ChunkedQueryTests(unittest.TestCase):
    def _run(self, env, rows_per_chunk=()):
        import app.llm_costs as lc

        queries: list[str] = []

        class FakeResult:
            def __init__(self, rows):
                self.result_rows = rows

        class FakeClient:
            def query(self, sql):
                queries.append(sql)
                return FakeResult(list(rows_per_chunk))

        with mock.patch.object(lc, "get_client", return_value=FakeClient()):
            payload = lc.get_daily_costs(
                since="2026-08-01", until="2026-08-14", env=env
            )
        return queries, payload

    def test_issues_one_query_per_day(self) -> None:
        queries, _ = self._run({})
        self.assertEqual(len(queries), 14)

    def test_chunk_size_reduces_query_count(self) -> None:
        queries, _ = self._run({"LLM_COST_CHUNK_DAYS": "14"})
        self.assertEqual(len(queries), 1)

    def test_each_chunk_pins_its_own_day(self) -> None:
        queries, _ = self._run({})
        self.assertIn("toDate('2026-08-01')", queries[0])
        self.assertIn("toDate('2026-08-02')", queries[0])
        self.assertIn("toDate('2026-08-14')", queries[-1])

    def test_boundary_margin_preserved_per_chunk(self) -> None:
        queries, _ = self._run({})
        self.assertIn("- INTERVAL 2 MINUTE", queries[0])
        self.assertIn("+ INTERVAL 2 MINUTE", queries[0])

    def test_rows_from_every_chunk_are_concatenated(self) -> None:
        row = ("2026-08-01", "gpt-4", "openai", "extract", 1.5, 3)
        _, payload = self._run({}, rows_per_chunk=(row,))
        self.assertEqual(len(payload["rows"]), 14)
        self.assertEqual(payload["rows"][0]["spend_usd"], 1.5)

    def test_connection_failure_wraps_as_llm_cost_error(self) -> None:
        """get_client() must stay inside the try; a driver exception here
        would otherwise escape as an unhandled error type."""
        import app.llm_costs as lc

        with mock.patch.object(
            lc, "get_client", side_effect=RuntimeError("name resolution failed")
        ):
            with self.assertRaises(lc.LlmCostError) as caught:
                lc.get_daily_costs(since="2026-08-01", until="2026-08-02", env={})
        self.assertIn("connection failed", str(caught.exception))

    def test_failing_chunk_names_its_date_range(self) -> None:
        import app.llm_costs as lc

        class BoomClient:
            def query(self, sql):
                raise RuntimeError("NOT_ENOUGH_SPACE")

        with mock.patch.object(lc, "get_client", return_value=BoomClient()):
            with self.assertRaises(lc.LlmCostError) as caught:
                lc.get_daily_costs(since="2026-08-01", until="2026-08-14", env={})
        self.assertIn("2026-08-01", str(caught.exception))
        self.assertIn("NOT_ENOUGH_SPACE", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
