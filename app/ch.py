"""ClickHouse client for aig.otel_traces."""
from __future__ import annotations

import os
from urllib.parse import urlparse

import clickhouse_connect
from clickhouse_connect.driver.client import Client


def _clickhouse_settings() -> dict[str, object]:
    """Prefer CLICKHOUSE_*; fall back to LLM_CLICKHOUSE_* from lemma env secret."""
    host = os.environ.get("CLICKHOUSE_HOST", "").strip()
    using_explicit_config = bool(host)
    port = os.environ.get("CLICKHOUSE_PORT", "").strip() if using_explicit_config else ""
    user = os.environ.get("CLICKHOUSE_USER", "").strip() if using_explicit_config else ""
    password = os.environ.get("CLICKHOUSE_PASSWORD", "") if using_explicit_config else ""
    database = (
        os.environ.get("CLICKHOUSE_DATABASE", "").strip()
        if using_explicit_config
        else ""
    )
    secure_raw = (
        os.environ.get("CLICKHOUSE_SECURE", "").strip()
        if using_explicit_config
        else ""
    )

    url = os.environ.get("LLM_CLICKHOUSE_URL", "").strip()
    if url and not using_explicit_config:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if parsed.port:
            port = str(parsed.port)
        secure_raw = "true" if parsed.scheme == "https" else "false"

    if not using_explicit_config:
        user = os.environ.get("LLM_CLICKHOUSE_USER", "").strip()
        password = os.environ.get("LLM_CLICKHOUSE_PASSWORD", "")
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
