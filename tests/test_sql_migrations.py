"""Shape checks for sql/005 (llm_usage reads llm_usage.raw) and sql/006 (content purge)."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

SQL = Path(__file__).resolve().parent.parent / "sql"
CONTENT_KEYS = (
    "gen_ai.input.messages",
    "gen_ai.output.messages",
    "gen_ai.prompt_json",
    "gen_ai.completion_json",
)


def _statement(name: str) -> str:
    text = (SQL / name).read_text(encoding="utf-8")
    return "\n".join(line for line in text.splitlines() if not line.startswith("--")).strip()


def _tuple_type(sql: str) -> str:
    match = re.search(r"llm_usage (Tuple\([^)]*\))", sql)
    assert match, "no llm_usage Tuple type"
    return match.group(1)


def _lambda(sql: str) -> str:
    start = sql.index("arrayMap(u ->")
    end = sql.index(", [", start)
    return sql[start:end]


class LlmUsageRawMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old = _statement("004_llm_usage.sql")
        self.new = _statement("005_llm_usage_raw.sql")

    def test_modifies_column_materialized(self) -> None:
        self.assertTrue(self.new.startswith("ALTER TABLE aig.otel_traces MODIFY COLUMN llm_usage"))
        self.assertIn("MATERIALIZED", self.new)
        self.assertEqual(self.new.count(";"), 0)

    def test_reads_raw_first_then_old_fallback(self) -> None:
        raw = self.new.index("SpanAttributes['llm_usage.raw']")
        fallback = self.new.index("SpanAttributes['gen_ai.completion_json']")
        self.assertLess(raw, fallback)
        self.assertIn("SpanAttributes['gen_ai.output.messages']", self.new)

    def test_parsing_logic_unchanged(self) -> None:
        self.assertEqual(_tuple_type(self.new), _tuple_type(self.old))
        self.assertEqual(_lambda(self.new), _lambda(self.old))


class PurgeMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sql = _statement("006_purge_llm_content.sql")

    def test_strips_exactly_the_four_keys(self) -> None:
        match = re.search(r"k NOT IN \(([^)]*)\)", self.sql)
        assert match
        self.assertEqual(set(re.findall(r"'([^']+)'", match.group(1))), set(CONTENT_KEYS))

    def test_preserves_usage_via_raw_key(self) -> None:
        self.assertIn("mapUpdate(SpanAttributes, map('llm_usage.raw'", self.sql)

    def test_single_partition_clause_between_assignment_and_where(self) -> None:
        self.assertEqual(self.sql.count("IN PARTITION ID '{partition_id}'"), 1)
        self.assertEqual(self.sql.count("{partition_id}"), 1)
        update = self.sql.index("UPDATE SpanAttributes =")
        part = self.sql.index("IN PARTITION ID")
        where = self.sql.index(" WHERE ")
        self.assertLess(update, part)
        self.assertLess(part, where)

    def test_where_selects_only_rows_with_content(self) -> None:
        where = self.sql[self.sql.index(" WHERE ") :]
        for key in CONTENT_KEYS:
            self.assertIn(f"mapContains(SpanAttributes, '{key}')", where)


if __name__ == "__main__":
    unittest.main()
