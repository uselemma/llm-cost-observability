from __future__ import annotations

import unittest
from datetime import date
from unittest import mock

from app.vendors import llm

AZURE_CREDS = {
    "AZURE_TENANT_ID": "tenant-1",
    "AZURE_CLIENT_ID": "client-1",
    "AZURE_CLIENT_SECRET": "secret-1",
    "AZURE_COST_SUBSCRIPTIONS": "prod:sub-prod",
}

LLM_ENV = {"LLM_CLICKHOUSE_URL": "https://ch.example"}


def _payload(rows):
    return {"rows": rows, "errors": []}


def _row(provider, spend=3.66, model="DeepSeek-V4-Flash"):
    return {
        "date": "2026-08-21",
        "model": model,
        "provider": provider,
        "feature": "",
        "spend_usd": spend,
        "calls": 1,
    }


class AzureOpenaiSkipTests(unittest.TestCase):
    def _fetch(self, env, rows):
        with mock.patch.object(llm, "get_daily_costs", return_value=_payload(rows)):
            return llm.fetch_with_coverage(
                date(2026, 8, 21), date(2026, 8, 22), env
            )

    def test_keeps_azure_openai_when_azure_vendor_is_off(self) -> None:
        rows, warning = self._fetch(
            LLM_ENV,
            [
                _row("azure-openai", 3.66),
                _row("openai", 1.0, model="gpt-4.1"),
            ],
        )
        self.assertIsNone(warning)
        providers = [row.provider for row in rows]
        self.assertEqual(providers, ["llm/azure-openai", "llm/openai"])

    def test_drops_azure_openai_only_when_azure_vendor_is_on(self) -> None:
        env = {**LLM_ENV, **AZURE_CREDS}
        rows, _ = self._fetch(
            env,
            [
                _row("azure-openai", 3.66),
                _row("Azure-OpenAI", 1.1, model="other-foundry"),
                _row("openai", 1.0, model="gpt-4.1"),
            ],
        )
        providers = [row.provider for row in rows]
        self.assertEqual(providers, ["llm/openai"])
        self.assertEqual(rows[0].cost_usd, 1.0)


if __name__ == "__main__":
    unittest.main()
