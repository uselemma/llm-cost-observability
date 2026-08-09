from __future__ import annotations

import unittest

from app.queries import (
    CF_EXACT_CACHE_HIT_EXPR,
    RAW_CALL_ID_EXPR,
    ROOT_FILTER,
    VERCEL_TAG_CALL_ID_EXPR,
    logical_calls_cte,
)


class LogicalCallsQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sql = logical_calls_cte("Timestamp >= now() - INTERVAL 1 HOUR")

    def test_extracts_direct_and_reporting_tag_call_ids(self) -> None:
        self.assertIn("SpanAttributes['call_id']", RAW_CALL_ID_EXPR)
        self.assertIn("vercel.ai_gateway.tags", VERCEL_TAG_CALL_ID_EXPR)
        self.assertIn("call:", VERCEL_TAG_CALL_ID_EXPR)

    def test_only_vercel_request_roots_enter_call_projection(self) -> None:
        self.assertIn("empty(ParentSpanId)", ROOT_FILTER)
        self.assertIn("service.namespace", ROOT_FILTER)

    def test_cloudflare_and_vercel_fields_have_explicit_ownership(self) -> None:
        for cloudflare_field in (
            "gen_ai.prompt_json",
            "gen_ai.completion_json",
            "feature",
            "prompt",
            "project_id",
            "experiment_variant",
        ):
            self.assertIn(cloudflare_field, self.sql)
        for vercel_field in (
            "vercel.ai_gateway.provider",
            "vercel.ai_gateway.generation.id",
            "vercel.ai_gateway.credential.type",
            "vercel.ai_gateway.cost.total",
            "vercel.ai_gateway.cost.market",
            "gen_ai.usage.reasoning.output_tokens",
            "gen_ai.usage.cache_read.input_tokens",
            "gen_ai.usage.cache_creation.input_tokens",
            "gen_ai.response.time_to_first_chunk",
            "vercel.ai_gateway.region",
            "vercel.ai_gateway.zdr.requested",
        ):
            self.assertIn(vercel_field, self.sql)

    def test_unreconciled_cost_is_excluded(self) -> None:
        self.assertIn("'unreconciled'", self.sql)
        self.assertIn("AS cost_included", self.sql)
        self.assertIn("AS spend_usd", self.sql)
        self.assertIn("vercel_billed_cost", self.sql)

    def test_exact_cache_hit_requires_explicit_marker(self) -> None:
        self.assertIn("= 'HIT'", CF_EXACT_CACHE_HIT_EXPR)
        self.assertNotIn("vercel_root_count", CF_EXACT_CACHE_HIT_EXPR)
        self.assertIn("exact_cache_hit, 0.", self.sql)

    def test_projection_exposes_two_minute_slo_inputs(self) -> None:
        self.assertIn("INTERVAL 2 MINUTE", self.sql)
        self.assertIn("AS reconciliation_overdue", self.sql)
        self.assertIn("AS reconciliation_ms", self.sql)


if __name__ == "__main__":
    unittest.main()
