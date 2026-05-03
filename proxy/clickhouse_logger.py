import json
import logging
import os

import clickhouse_connect
from litellm.integrations.custom_logger import CustomLogger

# Side-effect import: registers /api/* routes and /dashboard SPA serving on
# the LiteLLM FastAPI app. Imported here because clickhouse_logger is loaded
# at proxy startup via litellm_settings.callbacks.
import dashboard_api  # noqa: F401


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
    "cache_creation_tokens",
    "reasoning_tokens",
    "audio_tokens",
    "image_tokens",
    "total_tokens",
    "spend_usd",
    "latency_ms",
    "ttft_ms",
    "status",
    "finish_reason",
    "error_message",
    "num_retries",
    "temperature",
    "top_p",
    "max_tokens",
    "presence_penalty",
    "tags",
    "metadata",
    "input_messages",
    "output_text",
    "reasoning_content",
    "tool_calls",
]


def _int(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _get(obj, key, default=None):
    """Read a key from either a dict or an object's attribute."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


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
            usage = _get(response_obj, "usage") or {}
            litellm_md = (kwargs.get("litellm_params") or {}).get("metadata") or {}
            proxy_md = kwargs.get("metadata") or {}
            optional_params = kwargs.get("optional_params") or {}

            # Token usage — handle both flat and nested-details shapes.
            prompt_tokens = _int(_get(usage, "prompt_tokens"))
            completion_tokens = _int(_get(usage, "completion_tokens"))
            total_tokens = _int(_get(usage, "total_tokens"))
            cache_read = _int(_get(usage, "cache_read_input_tokens"))
            cache_creation = _int(_get(usage, "cache_creation_input_tokens"))

            ctd = _get(usage, "completion_tokens_details") or {}
            ptd = _get(usage, "prompt_tokens_details") or {}
            reasoning_tokens = _int(_get(usage, "reasoning_tokens") or _get(ctd, "reasoning_tokens"))
            audio_tokens = _int(_get(ptd, "audio_tokens") or _get(ctd, "audio_tokens"))
            image_tokens = _int(_get(ptd, "image_tokens") or _get(ctd, "image_tokens"))

            # TTFT — only meaningful for streams.
            completion_start = kwargs.get("completion_start_time")
            ttft_ms = 0
            if completion_start and start_time:
                try:
                    ttft_ms = int((completion_start - start_time).total_seconds() * 1000)
                except Exception:
                    ttft_ms = 0

            # Outcome
            finish_reason = ""
            tool_calls_json = ""
            output_text = ""
            reasoning_content = ""
            try:
                choice = response_obj.choices[0]
                finish_reason = getattr(choice, "finish_reason", "") or ""
                msg = choice.message
                output_text = getattr(msg, "content", "") or ""
                reasoning_content = getattr(msg, "reasoning_content", "") or ""
                tcs = getattr(msg, "tool_calls", None)
                if tcs:
                    tool_calls_json = json.dumps(
                        [tc.model_dump() if hasattr(tc, "model_dump") else dict(tc) for tc in tcs],
                        default=str,
                    )
            except (AttributeError, IndexError, TypeError):
                pass

            error_message = ""
            if status == "failure":
                exc = kwargs.get("exception") or response_obj
                if exc is not None:
                    if isinstance(exc, BaseException):
                        error_message = f"{type(exc).__name__}: {exc}"
                    else:
                        error_message = str(exc)
                    error_message = error_message[:4000]

            num_retries = _int(
                (kwargs.get("litellm_params") or {}).get("num_retries")
                or kwargs.get("num_retries")
            )

            # Tags — auth stamps env via team_alias; union with client tags.
            client_tags = proxy_md.get("tags") or litellm_md.get("tags") or []
            if not isinstance(client_tags, list):
                client_tags = []
            team = litellm_md.get("user_api_key_team_alias", "") or ""
            env_tag = [f"env:{team}"] if team else []
            tags = list(dict.fromkeys([*env_tag, *(str(t) for t in client_tags)]))

            input_messages = json.dumps(kwargs.get("messages") or [], default=str)

            row = [
                kwargs.get("litellm_call_id", "") or "",
                end_time,
                kwargs.get("model", "") or "",
                kwargs.get("custom_llm_provider", "") or "",
                litellm_md.get("user_api_key_alias", "") or "",
                team,
                str(proxy_md.get("user", "") or ""),
                prompt_tokens,
                completion_tokens,
                cache_read,
                cache_creation,
                reasoning_tokens,
                audio_tokens,
                image_tokens,
                total_tokens,
                float(kwargs.get("response_cost") or 0.0),
                int((end_time - start_time).total_seconds() * 1000),
                ttft_ms,
                status,
                finish_reason,
                error_message,
                num_retries,
                optional_params.get("temperature"),
                optional_params.get("top_p"),
                optional_params.get("max_tokens") or optional_params.get("max_completion_tokens"),
                optional_params.get("presence_penalty"),
                tags,
                json.dumps(proxy_md, default=str),
                input_messages,
                output_text,
                reasoning_content,
                tool_calls_json,
            ]

            self.client.insert(self.table, [row], column_names=COLUMN_NAMES)
        except Exception:
            log.exception("clickhouse_logger insert failed")


clickhouse_logger = ClickHouseLogger()
