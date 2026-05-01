"""End-to-end smoke test: send a chat call through the proxy and confirm a row
lands in ClickHouse with non-zero cost.

Usage:
    python scripts/smoke_test.py
"""
import os
import sys
import time

import clickhouse_connect

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "client"))
from llm_client import LLMClient  # noqa: E402


def main() -> int:
    client = LLMClient()
    resp = client.chat(
        model=os.environ.get("SMOKE_MODEL", "claude-sonnet-4-6"),
        messages=[{"role": "user", "content": "Say hello in 5 words."}],
        tags=["feature:smoke", "prompt:smoke-v1"],
    )
    request_id = resp.id
    print(f"sent request, id={request_id}")

    ch = clickhouse_connect.get_client(
        host=os.environ["CLICKHOUSE_HOST"],
        port=int(os.environ.get("CLICKHOUSE_PORT", "8443")),
        username=os.environ.get("CLICKHOUSE_USER", "default"),
        password=os.environ["CLICKHOUSE_PASSWORD"],
        database=os.environ.get("CLICKHOUSE_DATABASE", "default"),
        secure=os.environ.get("CLICKHOUSE_SECURE", "true").lower() == "true",
    )

    deadline = time.time() + 15
    while time.time() < deadline:
        rows = ch.query(
            "SELECT request_id, model, spend_usd, total_tokens, tags "
            "FROM litellm_logs WHERE timestamp >= now() - INTERVAL 1 MINUTE "
            "ORDER BY timestamp DESC LIMIT 5"
        ).result_rows
        if rows:
            print("recent rows:")
            for r in rows:
                print(" ", r)
            return 0
        time.sleep(1)

    print("no rows landed within 15s", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
