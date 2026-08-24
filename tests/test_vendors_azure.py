from __future__ import annotations

import unittest
from datetime import date
from unittest import mock

from app.vendors import azure
from app.vendors.base import ENV_DEV, ENV_PROD, VendorCostError

CREDS = {
    "AZURE_TENANT_ID": "tenant-1",
    "AZURE_CLIENT_ID": "client-1",
    "AZURE_CLIENT_SECRET": "secret-1",
    "AZURE_COST_SUBSCRIPTIONS": "prod:sub-prod,dev:sub-dev",
}

COLUMNS = [
    {"name": "Cost", "type": "Number"},
    {"name": "UsageDate", "type": "Number"},
    {"name": "ServiceName", "type": "String"},
    {"name": "MeterSubCategory", "type": "String"},
    {"name": "ChargeType", "type": "String"},
    {"name": "Currency", "type": "String"},
]


def _payload(rows, columns=None, next_link=None):
    properties = {"columns": columns or COLUMNS, "rows": rows}
    if next_link:
        properties["nextLink"] = next_link
    return {"properties": properties}


class RegistryTests(unittest.TestCase):
    def test_azure_is_registered(self) -> None:
        from app.vendors import VENDORS

        self.assertIs(VENDORS["azure"], azure)


class ConfigTests(unittest.TestCase):
    def test_requires_all_four_keys(self) -> None:
        self.assertTrue(azure.is_configured(CREDS))
        for key in azure.REQUIRED_ENV:
            partial = dict(CREDS)
            partial.pop(key)
            self.assertFalse(azure.is_configured(partial), key)

    def test_parses_subscription_pairs(self) -> None:
        subs = azure.list_subscriptions(CREDS)
        self.assertEqual(
            [(s.name, s.subscription_id) for s in subs],
            [("prod", "sub-prod"), ("dev", "sub-dev")],
        )

    def test_rejects_malformed_subscription_entry(self) -> None:
        with self.assertRaises(VendorCostError):
            azure.list_subscriptions({"AZURE_COST_SUBSCRIPTIONS": "no-colon"})


class ParseTests(unittest.TestCase):
    def test_foundry_meters_use_azure_foundry_and_meter_subcategory(self) -> None:
        payload = _payload(
            [
                [618.98, 20260821, "Foundry Models", "Input Tokens", "Usage", "USD"],
                [12.0, 20260821, "Azure OpenAI", "GPT deployments", "Usage", "USD"],
                [4.0, 20260821, "Cognitive Services", "Speech", "Usage", "USD"],
                [1.0, 20260821, "Azure AI Services", "Content Safety", "Usage", "USD"],
            ]
        )
        rows = azure.rows_from_payload(payload, "prod")
        self.assertEqual({row.provider for row in rows}, {"azure_foundry"})
        self.assertEqual(
            [row.service for row in rows],
            ["Input Tokens", "GPT deployments", "Speech", "Content Safety"],
        )
        self.assertEqual({row.env for row in rows}, {ENV_PROD})
        self.assertEqual(rows[0].date, "2026-08-21")
        self.assertEqual(rows[0].cost_usd, 618.98)

    def test_non_foundry_uses_azure_and_service_name(self) -> None:
        payload = _payload(
            [[40.0, 20260821, "Virtual Machines", "Dv5 Series", "Usage", "USD"]]
        )
        rows = azure.rows_from_payload(payload, "staging")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].provider, "azure")
        self.assertEqual(rows[0].service, "Virtual Machines")
        self.assertEqual(rows[0].env, ENV_DEV)

    def test_charge_type_usage_only(self) -> None:
        payload = _payload(
            [
                [10.0, 20260821, "Foundry Models", "Input Tokens", "Usage", "USD"],
                [-10.0, 20260821, "Foundry Models", "Input Tokens", "Refund", "USD"],
                [1000.0, 20260821, "Foundry Models", "Input Tokens", "Purchase", "USD"],
            ]
        )
        rows = azure.rows_from_payload(payload, "prod")
        self.assertEqual([row.cost_usd for row in rows], [10.0])

    def test_usage_date_iso_string_is_accepted(self) -> None:
        payload = _payload(
            [["3.5", "2026-08-13T00:00:00Z", "Storage", "Blob", "Usage", "USD"]]
        )
        rows = azure.rows_from_payload(payload, "prod")
        self.assertEqual(rows[0].date, "2026-08-13")
        self.assertEqual(rows[0].cost_usd, 3.5)


class QueryBodyTests(unittest.TestCase):
    def test_daily_actual_cost_filters_usage_and_maps_exclusive_end(self) -> None:
        body = azure._query_body(date(2026, 8, 10), date(2026, 8, 24))
        self.assertEqual(body["type"], "ActualCost")
        self.assertEqual(body["timeframe"], "Custom")
        self.assertEqual(body["timePeriod"], {"from": "2026-08-10", "to": "2026-08-23"})
        self.assertEqual(body["dataset"]["granularity"], "Daily")
        self.assertEqual(
            body["dataset"]["filter"]["dimensions"],
            {"name": "ChargeType", "operator": "In", "values": ["Usage"]},
        )
        self.assertEqual(
            [g["name"] for g in body["dataset"]["grouping"]],
            ["ServiceName", "MeterSubCategory"],
        )

    def test_chunks_beyond_daily_cap(self) -> None:
        windows = azure._windows(date(2026, 1, 1), date(2026, 3, 1))
        self.assertGreater(len(windows), 1)
        self.assertEqual(windows[0], (date(2026, 1, 1), date(2026, 2, 1)))
        self.assertEqual(windows[-1][1], date(2026, 3, 1))


class FetchTests(unittest.TestCase):
    def test_token_then_cost_query_and_foundry_split(self) -> None:
        captured: dict[str, object] = {}

        def fake_form(url, headers, fields, timeout=60):
            captured["token_url"] = url
            captured["token_fields"] = fields
            return {"access_token": "tok"}

        def fake_json(url, headers, body, timeout=60):
            captured.setdefault("query_urls", []).append(url)
            captured.setdefault("query_bodies", []).append(body)
            captured.setdefault("query_headers", []).append(headers)
            if "sub-prod" in url:
                return _payload(
                    [[982.62, 20260821, "Foundry Models", "Input Tokens", "Usage", "USD"]]
                )
            return _payload(
                [[15.0, 20260821, "Virtual Machines", "Dv5 Series", "Usage", "USD"]]
            )

        with mock.patch.object(azure, "post_form", side_effect=fake_form):
            with mock.patch.object(azure, "post_json", side_effect=fake_json):
                rows = azure.fetch(date(2026, 8, 21), date(2026, 8, 22), CREDS)

        self.assertIn("tenant-1/oauth2/v2.0/token", str(captured["token_url"]))
        self.assertEqual(captured["token_fields"]["grant_type"], "client_credentials")
        self.assertEqual(
            captured["token_fields"]["scope"], "https://management.azure.com/.default"
        )
        self.assertNotIn("secret-1", str(captured["token_url"]))
        urls = captured["query_urls"]
        self.assertTrue(any("sub-prod" in url and "api-version=2023-11-01" in url for url in urls))
        self.assertEqual(
            captured["query_headers"][0]["Authorization"], "Bearer tok"
        )
        body = captured["query_bodies"][0]
        self.assertEqual(body["dataset"]["filter"]["dimensions"]["values"], ["Usage"])

        by_provider = {row.provider: row for row in rows}
        self.assertEqual(by_provider["azure_foundry"].service, "Input Tokens")
        self.assertEqual(by_provider["azure_foundry"].env, ENV_PROD)
        self.assertEqual(by_provider["azure"].service, "Virtual Machines")
        self.assertEqual(by_provider["azure"].env, ENV_DEV)

    def test_missing_credentials_raise(self) -> None:
        with self.assertRaises(VendorCostError):
            azure.fetch(date(2026, 8, 13), date(2026, 8, 14), {})


if __name__ == "__main__":
    unittest.main()
