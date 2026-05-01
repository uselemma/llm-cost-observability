import json
import logging
import os

import clickhouse_connect
from litellm.integrations.custom_logger import CustomLogger

log = logging.getLogger("clickhouse_logger")

COLUMN_NAMES = [
    "request_id",
    "timestamp",
    "model",
    "provider",
    "api_key_alias",
    "team",
    "end_user",
    "prompt_tokens",
    "completion_tokens",
    "cache_read_tokens",
    "total_tokens",
    "spend_usd",
    "latency_ms",
    "status",
    "tags",
    "metadata",
    "input_messages",
    "output_text",
    "reasoning_content",
]


def _int(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


class ClickHouseLogger(CustomLogger):
    def __init__(self):
        self.client = clickhouse_connect.get_client(
            host=os.environ["CLICKHOUSE_HOST"],
            port=int(os.environ.get("CLICKHOUSE_PORT", "8443")),
            username=os.environ["CLICKHOUSE_USER"],
            password=os.environ["CLICKHOUSE_PASSWORD"],
            database=os.environ.get("CLICKHOUSE_DATABASE", "default"),
            secure=os.environ.get("CLICKHOUSE_SECURE", "true").lower() == "true",
            settings={"async_insert": 1, "wait_for_async_insert": 0},
        )
        self.table = os.environ.get("CLICKHOUSE_TABLE", "litellm_logs")

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        await self._write(kwargs, response_obj, start_time, end_time, "success")

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        await self._write(kwargs, response_obj, start_time, end_time, "failure")

    async def _write(self, kwargs, response_obj, start_time, end_time, status):
        try:
            usage = getattr(response_obj, "usage", None) or {}
            litellm_md = (kwargs.get("litellm_params") or {}).get("metadata") or {}
            proxy_md = kwargs.get("metadata") or {}

            input_messages = json.dumps(kwargs.get("messages") or [], default=str)
            output_text = ""
            reasoning_content = ""
            try:
                msg = response_obj.choices[0].message
                output_text = getattr(msg, "content", "") or ""
                reasoning_content = getattr(msg, "reasoning_content", "") or ""
            except (AttributeError, IndexError, TypeError):
                pass

            client_tags = proxy_md.get("tags") or litellm_md.get("tags") or []
            if not isinstance(client_tags, list):
                client_tags = []
            team = litellm_md.get("user_api_key_team_alias", "") or ""
            env_tag = [f"env:{team}"] if team else []
            # dedup, preserve order
            tags = list(dict.fromkeys([*env_tag, *(str(t) for t in client_tags)]))

            row = [
                kwargs.get("litellm_call_id", "") or "",
                end_time,
                kwargs.get("model", "") or "",
                kwargs.get("custom_llm_provider", "") or "",
                litellm_md.get("user_api_key_alias", "") or "",
                litellm_md.get("user_api_key_team_alias", "") or "",
                str(proxy_md.get("user", "") or ""),
                _int(getattr(usage, "prompt_tokens", 0) if not isinstance(usage, dict) else usage.get("prompt_tokens")),
                _int(getattr(usage, "completion_tokens", 0) if not isinstance(usage, dict) else usage.get("completion_tokens")),
                _int(getattr(usage, "cache_read_input_tokens", 0) if not isinstance(usage, dict) else usage.get("cache_read_input_tokens")),
                _int(getattr(usage, "total_tokens", 0) if not isinstance(usage, dict) else usage.get("total_tokens")),
                float(kwargs.get("response_cost") or 0.0),
                int((end_time - start_time).total_seconds() * 1000),
                status,
                tags,
                json.dumps(proxy_md, default=str),
                input_messages,
                output_text,
                reasoning_content,
            ]

            self.client.insert(self.table, [row], column_names=COLUMN_NAMES)
        except Exception:
            log.exception("clickhouse_logger insert failed")


clickhouse_logger = ClickHouseLogger()
