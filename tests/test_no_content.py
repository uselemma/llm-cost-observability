"""Prompt and response content is not stored (ENG-2244), so no query or API may touch it."""
from __future__ import annotations

import unittest
from typing import Any
from unittest import mock

from fastapi.testclient import TestClient

from app import queries, span_queries
from app.cel_filter import compile_cel_filter
from app.main import app

CONTENT_KEYS = (
    "gen_ai.input.messages",
    "gen_ai.output.messages",
    "gen_ai.prompt_json",
    "gen_ai.completion_json",
)


def _without_strip_list(sql: str) -> str:
    return sql.replace(queries.STRIPPED_ATTRIBUTES_JSON, "")


class _FakeResult:
    column_names: list[str] = []
    result_rows: list[tuple[Any, ...]] = []


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def query(self, sql: str, parameters: dict[str, Any] | None = None) -> _FakeResult:
        self.calls.append((sql, parameters or {}))
        return _FakeResult()


class SqlIsContentFreeTests(unittest.TestCase):
    def test_strip_constant_lists_exactly_the_four_keys(self) -> None:
        self.assertEqual(set(queries.CONTENT_ATTRIBUTE_KEYS), set(CONTENT_KEYS))
        for key in CONTENT_KEYS:
            self.assertIn(f"'{key}'", queries.STRIPPED_ATTRIBUTES_JSON)
        self.assertIn("mapFilter", queries.STRIPPED_ATTRIBUTES_JSON)

    def test_query_modules_never_name_content_keys(self) -> None:
        strings = {
            "logical_calls_cte": queries.logical_calls_cte("Timestamp > now()"),
            "queries.LIST_SELECT": queries.LIST_SELECT,
            "queries.DETAIL_SELECT": queries.DETAIL_SELECT,
            "queries.ATTEMPTS_SELECT": queries.ATTEMPTS_SELECT,
        }
        for name, value in vars(span_queries).items():
            if isinstance(value, str):
                strings[f"span_queries.{name}"] = value
            elif isinstance(value, dict):
                strings[f"span_queries.{name}"] = repr(value)
        for name, sql in strings.items():
            for key in CONTENT_KEYS:
                self.assertNotIn(key, _without_strip_list(sql), f"{name} reads {key}")

    def test_content_columns_are_not_selected(self) -> None:
        for sql in (queries.LIST_SELECT, queries.DETAIL_SELECT, queries.logical_calls_cte()):
            for alias in (
                "input_messages",
                "output_text",
                "output_preview",
                "reasoning_content",
                "tool_calls",
                "cf_prompt_json",
                "cf_completion_json",
            ):
                self.assertNotIn(alias, sql)

    def test_metadata_is_filtered_server_side(self) -> None:
        for sql in (queries.DETAIL_SELECT, queries.ATTEMPTS_SELECT):
            self.assertIn(f"{queries.STRIPPED_ATTRIBUTES_JSON} AS metadata", sql)
            self.assertNotIn("toJSONString(SpanAttributes)", sql)


class CelContentKeyTests(unittest.TestCase):
    def test_compiler_rejects_content_keys(self) -> None:
        for key in CONTENT_KEYS:
            for expr in (
                f'metadata.{key} == "x"',
                f'"x" == metadata.{key}',
                f"has(metadata.{key})",
                f'contains(metadata.{key}, "x")',
            ):
                with self.subTest(expr=expr):
                    with self.assertRaises(ValueError) as ctx:
                        compile_cel_filter(expr)
                    self.assertIn(key, str(ctx.exception))
                    self.assertIn("not stored", str(ctx.exception))

    def test_other_metadata_keys_still_compile(self) -> None:
        sql, params = compile_cel_filter('metadata.feature == "x"')
        self.assertIn("SpanAttributes", sql)
        self.assertIn("feature", params.values())

    def test_endpoint_returns_422_naming_the_key(self) -> None:
        client = _FakeClient()
        with mock.patch("app.main.get_client", return_value=client):
            resp = TestClient(app).get(
                "/api/calls", params={"cel": 'metadata.gen_ai.input.messages == "x"'}
            )
        self.assertEqual(resp.status_code, 422)
        self.assertIn("gen_ai.input.messages", resp.json()["detail"])
        self.assertEqual(client.calls, [])


class SearchTests(unittest.TestCase):
    def test_q_matches_identifiers_not_content(self) -> None:
        client = _FakeClient()
        with mock.patch("app.main.get_client", return_value=client):
            resp = TestClient(app).get("/api/calls", params={"q": "needle"})
        self.assertEqual(resp.status_code, 200)
        sql, params = client.calls[0]
        self.assertEqual(params["q"], "needle")
        self.assertEqual(sql.count("{q:String}"), 4)
        for column in ("request_id", "call_id", "model"):
            self.assertRegex(sql, rf"positionCaseInsensitive\(\(?{column}\b")
        self.assertRegex(
            sql, r"arrayExists\(t -> positionCaseInsensitive\(t, \{q:String\}\) > 0, \(?tags\)?\)"
        )
        for key in CONTENT_KEYS:
            self.assertNotIn(key, sql)
        for alias in ("input_messages", "output_text"):
            self.assertNotIn(alias, sql)


if __name__ == "__main__":
    unittest.main()
