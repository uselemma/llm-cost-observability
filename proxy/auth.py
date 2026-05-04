"""Static, env-var-driven auth for LiteLLM proxy. No Postgres required.

Format:
    LITELLM_KEYS="sk-...:dev,sk-...:prod"

Each entry is `<secret>:<env>`. Services authenticate by sending the secret
as a bearer token. The matching env is attached as a tag on every request so
ClickHouse rows are server-side-stamped with `env:dev|prod`.
"""
from __future__ import annotations

import hashlib
import json
import os

from fastapi import HTTPException, Request
from litellm.proxy._types import UserAPIKeyAuth


def _parse_keys(raw: str) -> dict[str, str]:
    env_by_secret: dict[str, str] = {}
    for entry in (e.strip() for e in raw.split(",") if e.strip()):
        sk, _, env = entry.partition(":")
        if not sk or not env:
            raise ValueError(f"LITELLM_KEYS entry must be 'sk:env', got {entry!r}")
        if sk in env_by_secret:
            raise ValueError("duplicate secret in LITELLM_KEYS")
        env_by_secret[sk] = env
    if not env_by_secret:
        raise ValueError("LITELLM_KEYS is empty")
    return env_by_secret


_KEYS = _parse_keys(os.environ["LITELLM_KEYS"])


def _is_fireworks_model(model: object) -> bool:
    if not isinstance(model, str):
        return False
    return model.startswith(("fireworks/", "fireworks_ai/", "accounts/fireworks/"))


def _user_from_tags(tags: object) -> str | None:
    if not isinstance(tags, list):
        return None

    stable_tag_set: set[str] = set()
    for tag in tags:
        tag_str = str(tag).strip()
        if tag_str and not tag_str.startswith("env:"):
            stable_tag_set.add(tag_str)

    stable_tags = sorted(stable_tag_set)
    if not stable_tags:
        return None

    digest = hashlib.sha256("\n".join(stable_tags).encode("utf-8")).hexdigest()[:16]
    return f"tags:{digest}"


def _replace_request_body(request: Request, body: dict) -> None:
    body_bytes = json.dumps(body, separators=(",", ":")).encode("utf-8")

    async def receive() -> dict:
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    request._body = body_bytes
    request._json = body
    request._receive = receive


async def _set_fireworks_affinity_user(request: Request) -> None:
    """Set Fireworks' OpenAI-compatible `user` field from stable tags.

    Fireworks uses `user` for replica affinity, which improves prompt-cache hit
    rates when repeated calls share the same prompt prefix.
    """
    try:
        body_bytes = await request.body()
        if not body_bytes:
            return
        body = json.loads(body_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return

    if (
        not isinstance(body, dict)
        or body.get("user")
        or not _is_fireworks_model(body.get("model"))
    ):
        return

    metadata = body.get("metadata") or {}
    if not isinstance(metadata, dict):
        return

    user = _user_from_tags(metadata.get("tags"))
    if not user:
        return

    body["user"] = user
    _replace_request_body(request, body)


async def user_api_key_auth(request: Request, api_key: str) -> UserAPIKeyAuth:
    token = (api_key or "").removeprefix("Bearer ").strip()
    env = _KEYS.get(token)
    if env is None:
        raise HTTPException(status_code=401, detail="invalid api key")

    await _set_fireworks_affinity_user(request)

    # `env` is stamped server-side via team_alias and read back by the
    # ClickHouse logger.
    # `allow_client_tags=True` opts this key into accepting client-supplied
    # `metadata.tags` — without it, LiteLLM silently strips them.
    return UserAPIKeyAuth(
        api_key=token,
        team_alias=env,
        metadata={"allow_client_tags": True},
    )
