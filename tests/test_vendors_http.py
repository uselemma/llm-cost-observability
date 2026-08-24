from __future__ import annotations

import json
import unittest
from unittest import mock
from urllib.parse import parse_qs

from app.vendors import _http


class _FakeResponse:
    def __init__(self, body: str, headers: dict | None = None):
        self._body = body.encode("utf-8")
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args) -> bool:
        return False


class PostHelperTests(unittest.TestCase):
    def test_post_json_sends_json_body(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(request, timeout=60):
            captured["method"] = request.get_method()
            captured["data"] = request.data
            captured["content_type"] = request.get_header("Content-type")
            captured["timeout"] = timeout
            return _FakeResponse('{"ok": true}')

        with mock.patch("app.vendors._http.urllib.request.urlopen", side_effect=fake_urlopen):
            payload = _http.post_json(
                "https://example.test/query",
                {"Authorization": "Bearer tok"},
                {"type": "ActualCost"},
            )

        self.assertEqual(payload, {"ok": True})
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["content_type"], "application/json")
        self.assertEqual(json.loads(captured["data"]), {"type": "ActualCost"})

    def test_post_form_sends_urlencoded_token_fields(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(request, timeout=60):
            captured["method"] = request.get_method()
            captured["data"] = request.data
            captured["content_type"] = request.get_header("Content-type")
            return _FakeResponse('{"access_token": "tok"}')

        with mock.patch("app.vendors._http.urllib.request.urlopen", side_effect=fake_urlopen):
            payload = _http.post_form(
                "https://login.example/token",
                {},
                {
                    "grant_type": "client_credentials",
                    "client_id": "id",
                    "client_secret": "secret",
                    "scope": "https://management.azure.com/.default",
                },
            )

        self.assertEqual(payload["access_token"], "tok")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(
            captured["content_type"], "application/x-www-form-urlencoded"
        )
        fields = parse_qs(captured["data"].decode("utf-8"))
        self.assertEqual(fields["grant_type"], ["client_credentials"])
        self.assertEqual(fields["scope"], ["https://management.azure.com/.default"])

    def test_get_json_still_uses_get(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(request, timeout=60):
            captured["method"] = request.get_method()
            captured["data"] = request.data
            return _FakeResponse('{"result": 1}')

        with mock.patch("app.vendors._http.urllib.request.urlopen", side_effect=fake_urlopen):
            payload = _http.get_json("https://example.test/usage", {})

        self.assertEqual(payload, {"result": 1})
        self.assertEqual(captured["method"], "GET")
        self.assertIsNone(captured["data"])


if __name__ == "__main__":
    unittest.main()
