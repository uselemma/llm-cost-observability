from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.queries import ATTEMPTS_SELECT, logical_calls_cte

FIXTURE = Path(__file__).parent / "fixtures" / "dual_gateway_spans.json"


class DocumentedSpanFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.projection = logical_calls_cte()

    def test_roots_share_call_identity_through_documented_encodings(self) -> None:
        call_id = self.fixture["call_id"]
        self.assertEqual(
            self.fixture["cloudflare_root"]["span_attributes"]["call_id"],
            call_id,
        )
        self.assertIn(
            f"call:{call_id}",
            self.fixture["vercel_root"]["span_attributes"][
                "vercel.ai_gateway.tags"
            ],
        )

    def test_fixture_attributes_are_consumed_by_projection(self) -> None:
        attributes = {
            **self.fixture["cloudflare_root"]["span_attributes"],
            **self.fixture["vercel_root"]["span_attributes"],
        }
        for attribute in attributes:
            if attribute == "call_id":
                continue
            self.assertIn(attribute, self.projection)

    def test_attempts_are_not_roots_and_have_detail_fields(self) -> None:
        self.assertIn("toJSONString(SpanAttributes) AS metadata", ATTEMPTS_SELECT)
        for attempt in self.fixture["attempts"]:
            self.assertTrue(attempt["parent_span_id"])
            for attribute in attempt["span_attributes"]:
                if attribute.startswith(("gen_ai.", "vercel.ai_gateway.attempt.")):
                    self.assertIn(attribute, ATTEMPTS_SELECT)


if __name__ == "__main__":
    unittest.main()
