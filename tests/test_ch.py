from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.ch import _clickhouse_settings


class ClickHouseSettingsTests(unittest.TestCase):
    def test_llm_config_is_not_mixed_with_generic_product_credentials(self) -> None:
        env = {
            "CLICKHOUSE_USER": "product-user",
            "CLICKHOUSE_PASSWORD": "product-password",
            "CLICKHOUSE_DATABASE": "product",
            "LLM_CLICKHOUSE_URL": "https://llm.example.com:8443",
            "LLM_CLICKHOUSE_USER": "llm-user",
            "LLM_CLICKHOUSE_PASSWORD": "llm-password",
            "LLM_CLICKHOUSE_DATABASE": "aig",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = _clickhouse_settings()

        self.assertEqual(settings["host"], "llm.example.com")
        self.assertEqual(settings["username"], "llm-user")
        self.assertEqual(settings["password"], "llm-password")
        self.assertEqual(settings["database"], "aig")

    def test_complete_explicit_config_wins(self) -> None:
        env = {
            "CLICKHOUSE_HOST": "explicit.example.com",
            "CLICKHOUSE_PORT": "9440",
            "CLICKHOUSE_USER": "explicit-user",
            "CLICKHOUSE_PASSWORD": "explicit-password",
            "CLICKHOUSE_DATABASE": "explicit-db",
            "CLICKHOUSE_SECURE": "false",
            "LLM_CLICKHOUSE_URL": "https://llm.example.com:8443",
            "LLM_CLICKHOUSE_USER": "llm-user",
            "LLM_CLICKHOUSE_PASSWORD": "llm-password",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = _clickhouse_settings()

        self.assertEqual(settings["host"], "explicit.example.com")
        self.assertEqual(settings["port"], 9440)
        self.assertEqual(settings["username"], "explicit-user")
        self.assertFalse(settings["secure"])


if __name__ == "__main__":
    unittest.main()
