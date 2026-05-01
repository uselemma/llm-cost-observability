"""Thin wrapper around the OpenAI SDK that enforces the tagging contract.

Every service should import LLMClient and call it instead of constructing an
OpenAI client directly. The wrapper points at the LiteLLM proxy and asserts
that required tags are present on every call.
"""
from __future__ import annotations

import os
from typing import Any, Iterable

from openai import AsyncOpenAI, OpenAI

REQUIRED_KEYS = {"feature", "prompt"}
OPTIONAL_KEYS = {"customer", "experiment"}
# `env` is stamped server-side by the proxy auth hook from the API key, not
# trusted from the client. Clients that pass `env:...` will be rejected.
KNOWN_KEYS = REQUIRED_KEYS | OPTIONAL_KEYS

MAX_TAG_VALUE_LEN = 128


class TagValidationError(ValueError):
    pass


def _validate_tags(tags: Iterable[str]) -> list[str]:
    tags = list(tags)
    seen_keys: set[str] = set()
    for t in tags:
        if not isinstance(t, str) or ":" not in t:
            raise TagValidationError(f"tag must be 'key:value', got {t!r}")
        key, _, value = t.partition(":")
        if not key or not value:
            raise TagValidationError(f"tag must be 'key:value', got {t!r}")
        if key not in KNOWN_KEYS:
            raise TagValidationError(
                f"unknown tag key {key!r}; allowed: {sorted(KNOWN_KEYS)}"
            )
        if len(value) > MAX_TAG_VALUE_LEN:
            raise TagValidationError(f"tag value too long for {key!r}")
        seen_keys.add(key)

    missing = REQUIRED_KEYS - seen_keys
    if missing:
        raise TagValidationError(f"missing required tag keys: {sorted(missing)}")
    return tags


class LLMClient:
    """OpenAI-compatible client pointed at LiteLLM, with tag enforcement."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        async_client: bool = False,
    ):
        base_url = base_url or os.environ.get("LITELLM_BASE_URL", "http://litellm-proxy.internal:4000")
        api_key = api_key or os.environ["LITELLM_API_KEY"]
        cls = AsyncOpenAI if async_client else OpenAI
        self._client = cls(base_url=base_url, api_key=api_key)

    def chat(self, *, model: str, messages: list[dict], tags: list[str], user: str | None = None, **kwargs: Any):
        validated = _validate_tags(tags)
        metadata = kwargs.pop("metadata", {}) or {}
        metadata["tags"] = validated
        if user is not None:
            metadata["user"] = user
        return self._client.chat.completions.create(
            model=model,
            messages=messages,
            extra_body={"metadata": metadata},
            **kwargs,
        )
