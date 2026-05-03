"""Static, env-var-driven auth for LiteLLM proxy. No Postgres required.

Format:
    LITELLM_KEYS="sk-...:dev,sk-...:prod"

Each entry is `<secret>:<env>`. Services authenticate by sending the secret
as a bearer token. The matching env is attached as a tag on every request so
ClickHouse rows are server-side-stamped with `env:dev|prod`.
"""
from __future__ import annotations

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


async def user_api_key_auth(request: Request, api_key: str) -> UserAPIKeyAuth:
    token = (api_key or "").removeprefix("Bearer ").strip()
    env = _KEYS.get(token)
    if env is None:
        raise HTTPException(status_code=401, detail="invalid api key")

    # `env` is stamped server-side via team_alias and read back by the
    # ClickHouse logger.
    # `allow_client_tags=True` opts this key into accepting client-supplied
    # `metadata.tags` — without it, LiteLLM silently strips them.
    return UserAPIKeyAuth(
        api_key=token,
        team_alias=env,
        metadata={"allow_client_tags": True},
    )
