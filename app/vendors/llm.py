"""LLM spend as a unified-cost provider, from our own gateway telemetry.

Adapter over app.llm_costs, which rolls up the ENG-655 logical-call
projection so dual-gateway (Cloudflare + Vercel) roots are never
double-counted. Rows are marked SOURCE_DERIVED, not metered: for calls
reconciled against Vercel this is their billed figure, but for legacy
Cloudflare-only calls it is our own token-price estimate, and no invoice has
confirmed either.

The provider dimension is the *model* provider (openai, anthropic, ...)
rather than the gateway, because that is who ultimately bills for the tokens.
The gateway's own fee, where one exists, arrives through app.vendors.vercel /
app.vendors.cloudflare instead.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.llm_costs import LlmCostError, get_daily_costs
from app.vendors.base import (
    ENV_PROD,
    SOURCE_DERIVED,
    CostRow,
    VendorCostError,
)

PROVIDER = "llm"
UNKNOWN_PROVIDER = "unknown"


def is_configured(env: dict[str, str] | None = None) -> bool:
    """Needs ClickHouse credentials; app.ch raises if they are absent."""
    from app.vendors.base import env_get

    return bool(env_get(env, "LLM_CLICKHOUSE_URL"))


def _provider_name(raw: str) -> str:
    """Namespace the model provider so it can't collide with a SaaS bill.

    "openai" here means *tokens billed by OpenAI*, which is a different line
    item from a hypothetical OpenAI platform subscription; keeping the llm/
    prefix makes that unambiguous on the dashboard legend.
    """
    cleaned = (raw or "").strip().lower() or UNKNOWN_PROVIDER
    return f"llm/{cleaned}"


def fetch(
    start: date, end: date, env: dict[str, str] | None = None
) -> list[CostRow]:
    try:
        payload = get_daily_costs(
            since=start.isoformat(),
            until=(end - timedelta(days=1)).isoformat(),
            env=env,
        )
    except LlmCostError as exc:
        raise VendorCostError(str(exc)) from exc

    return [
        CostRow(
            date=str(row["date"]),
            provider=_provider_name(str(row["provider"])),
            # Model is the meaningful "service" unit for token spend -- it is
            # what you would switch to change the bill.
            service=str(row["model"]),
            cost_usd=float(row["spend_usd"]),
            source=SOURCE_DERIVED,
            # All gateway traffic in aig.otel_traces is prod; there is no dev
            # AI Gateway (see infra/aig-otel-collector).
            env=ENV_PROD,
        )
        for row in payload["rows"]
        if float(row["spend_usd"]) != 0
    ]
