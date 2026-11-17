"""Shape checks for sql/005 (llm_usage reads llm_usage.raw) and sql/006 (content purge)."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests._content_keys import CONTENT_KEYS

SQL = Path(__file__).resolve().parent.parent / "sql"


def _statement(name: str) -> str:
    text = (SQL / name).read_text(encoding="utf-8")
    return "\n".join(line for line in text.splitlines() if not line.startswith("--")).strip()


def _squash(sql: str) -> str:
    """Drop all whitespace so multi-line formatting compares equal to 004's single line."""
    return re.sub(r"\s+", "", sql)


def _tuple_type(sql: str) -> str:
    match = re.search(r"llm_usage(Tuple\([^)]*\))", _squash(sql))
    assert match, "no llm_usage Tuple type"
    return match.group(1)


def _lambda(sql: str) -> str:
    squashed = _squash(sql)
    start = squashed.index("arrayMap(u->")
    end = squashed.index(",[", start)
    return squashed[start:end]


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


USAGE_EXPR = (
    "JSONExtractRaw(if(SpanAttributes['gen_ai.completion_json']!='',"
    "SpanAttributes['gen_ai.completion_json'],SpanAttributes['gen_ai.output.messages']),'usage')"
)


class PurgeMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sql = _statement("006_purge_llm_content.sql")
        self.flat = _squash(self.sql)

    def test_strips_exactly_the_four_keys(self) -> None:
        match = re.search(r"kNOTIN\(([^)]*)\)", self.flat)
        assert match
        self.assertEqual(set(re.findall(r"'([^']+)'", match.group(1))), set(CONTENT_KEYS))

    def test_usage_is_written_to_raw_key_once_and_matches_005(self) -> None:
        self.assertIn("mapUpdate(SpanAttributes,map('llm_usage.raw',", self.flat)
        self.assertEqual(self.flat.count(USAGE_EXPR), 1)
        self.assertEqual(_squash(_statement("005_llm_usage_raw.sql")).count(USAGE_EXPR), 1)
        # An existing llm_usage.raw wins over re-extraction.
        self.assertIn("if(SpanAttributes['llm_usage.raw']!='',SpanAttributes['llm_usage.raw'],", self.flat)

    def test_single_partition_clause_between_assignment_and_where(self) -> None:
        self.assertEqual(self.flat.count("INPARTITIONID'{partition_id}'"), 1)
        self.assertEqual(self.flat.count("{partition_id}"), 1)
        update = self.flat.index("UPDATESpanAttributes=")
        part = self.flat.index("INPARTITIONID")
        where = self.flat.index("WHEREmapContains")
        self.assertLess(update, part)
        self.assertLess(part, where)

    def test_where_selects_only_rows_with_content(self) -> None:
        where = self.flat[self.flat.index("WHEREmapContains") :]
        for key in CONTENT_KEYS:
            self.assertIn(f"mapContains(SpanAttributes,'{key}')", where)
        self.assertEqual(where.count("mapContains"), 4)


if __name__ == "__main__":
    unittest.main()
