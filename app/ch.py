"""ClickHouse client for aig.otel_traces."""
from __future__ import annotations

import os
from urllib.parse import urlparse

import clickhouse_connect
from clickhouse_connect.driver.client import Client


def _clickhouse_settings() -> dict[str, object]:
    """Prefer CLICKHOUSE_*; fall back to LLM_CLICKHOUSE_* from lemma env secret."""
    host = os.environ.get("CLICKHOUSE_HOST", "").strip()
    port = os.environ.get("CLICKHOUSE_PORT", "").strip()
    user = os.environ.get("CLICKHOUSE_USER", "").strip()
    password = os.environ.get("CLICKHOUSE_PASSWORD", "")
    database = os.environ.get("CLICKHOUSE_DATABASE", "").strip()
    secure_raw = os.environ.get("CLICKHOUSE_SECURE", "").strip()

    url = os.environ.get("LLM_CLICKHOUSE_URL", "").strip()
    if url and not host:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if not port and parsed.port:
            port = str(parsed.port)
        if not secure_raw:
            secure_raw = "true" if parsed.scheme == "https" else "false"

    if not user:
        user = os.environ.get("LLM_CLICKHOUSE_USER", "").strip()
    if not password:
        password = os.environ.get("LLM_CLICKHOUSE_PASSWORD", "")
    if not database:
        database = os.environ.get("LLM_CLICKHOUSE_DATABASE", "aig").strip() or "aig"

    if not host:
        raise RuntimeError("CLICKHOUSE_HOST or LLM_CLICKHOUSE_URL is required")
    if not user:
        raise RuntimeError("CLICKHOUSE_USER or LLM_CLICKHOUSE_USER is required")

    return {
        "host": host,
        "port": int(port or "8443"),
        "username": user,
        "password": password,
        "database": database or "aig",
        "secure": (secure_raw or "true").lower() == "true",
    }


def get_client() -> Client:
    return clickhouse_connect.get_client(**_clickhouse_settings())
