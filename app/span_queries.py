"""SQL expressions over single spans (aig.otel_traces) for the usage stats endpoints.

These read the materialized llm_meta/llm_usage columns, so they stay fast over wide windows.
The Calls page uses app.queries (logical calls) instead."""
from __future__ import annotations

# Base filter for all dashboard queries.
SERVICE_FILTER = "ServiceName = 'ai-gateway'"

# Attribute helpers — CF docs use gen_ai.model.provider / prompt_json;
# some exporters use gen_ai.provider.name / input.messages. Prefer CF, fall back.
#
# The hot fields are read from the materialized `llm_meta` tuple column rather than
# SpanAttributes: reading any map key decompresses the whole map, which also holds
# the prompt/completion bodies (~98% of the table). See sql/003_llm_meta.sql.
MODEL_EXPR = "llm_meta.model"
PROVIDER_EXPR = "llm_meta.provider"
# Cost of a call: what the gateway recorded, else the cost the upstream billed (response body), else (custom providers,
# embeddings), tokens x the models.dev price for that provider/model (see app/pricing.py).
# Cached input is priced at the cache-read rate and cache writes at the cache-write rate;
# the cache counts come from llm_usage (sql/004_llm_usage.sql), parsed once from the response
# body. Without them, cache-heavy traffic would be overstated several-fold.
# The price arrays are query parameters: every query using SPEND_EXPR must bind
# pricing.query_params().
_PRICED_KEY = "concat(llm_meta.provider, '|', llm_meta.model)"


def _px(param: str) -> str:
    return f"transform({_PRICED_KEY}, {{px_keys:Array(String)}}, {{{param}:Array(Float64)}}, 0.)"


# Some providers count cache tokens inside input_tokens, others report them separately.
_FRESH_INPUT = (
    "if(llm_usage.cached + llm_usage.cache_write <= llm_meta.input_tokens, "
    "llm_meta.input_tokens - llm_usage.cached - llm_usage.cache_write, llm_meta.input_tokens)"
)
SPEND_EXPR = (
    "multiIf(llm_meta.cost > 0, llm_meta.cost, "
    # Cost the upstream gateway (e.g. Vercel) billed, from the response body usage.
    "llm_usage.reported_cost > 0, llm_usage.reported_cost, "
    f"{_FRESH_INPUT} * {_px('px_in')} + llm_usage.cached * {_px('px_cr')} "
    f"+ llm_usage.cache_write * {_px('px_cw')} + llm_meta.output_tokens * {_px('px_out')})"
)
PROMPT_TOKENS_EXPR = "llm_meta.input_tokens"
COMPLETION_TOKENS_EXPR = "llm_meta.output_tokens"
TOTAL_TOKENS_EXPR = f"({PROMPT_TOKENS_EXPR} + {COMPLETION_TOKENS_EXPR})"
LATENCY_MS_EXPR = "toUInt32(intDiv(Duration, 1000000))"
STATUS_EXPR = (
    "if(StatusCode = 'STATUS_CODE_ERROR', 'failure', 'success')"
)
INPUT_MESSAGES_EXPR = (
    "if(SpanAttributes['gen_ai.prompt_json'] != '', "
    "SpanAttributes['gen_ai.prompt_json'], "
    "SpanAttributes['gen_ai.input.messages'])"
)
OUTPUT_TEXT_EXPR = (
    "if(SpanAttributes['gen_ai.completion_json'] != '', "
    "SpanAttributes['gen_ai.completion_json'], "
    "SpanAttributes['gen_ai.output.messages'])"
)

# Reconstruct feature:/prompt:/variant:/project_id: tags from CF metadata attrs.
# Reads llm_meta (not SpanAttributes) so tag filters and /api/tags avoid the body-heavy map.
TAGS_EXPR = """arrayFilter(
    x -> x != '',
    [
        if(llm_meta.feature != '', concat('feature:', llm_meta.feature), ''),
        if(llm_meta.prompt != '', concat('prompt:', llm_meta.prompt), ''),
        if(llm_meta.variant != '', concat('variant:', llm_meta.variant), ''),
        if(llm_meta.project_id != '', concat('project_id:', llm_meta.project_id), '')
    ]
)"""

# Dimensions the stats endpoints can group/filter by. Empty string = untagged.
# `feature` is colon-hierarchical (parent:sub), so feature_parent rolls it up.
FEATURE_EXPR = "llm_meta.feature"
DIMENSION_EXPR: dict[str, str] = {
    "model": MODEL_EXPR,
    "provider": PROVIDER_EXPR,
    "feature": FEATURE_EXPR,
    "feature_parent": f"splitByChar(':', {FEATURE_EXPR})[1]",
    "prompt": "llm_meta.prompt",
    "project_id": "llm_meta.project_id",
    "variant": "llm_meta.variant",
    "status": STATUS_EXPR,
}
FILTER_DIMENSIONS = list(DIMENSION_EXPR)

ERROR_PRED = "StatusCode = 'STATUS_CODE_ERROR'"

# Failed calls are excluded from spend rollups (cost is only billed on success).
STATS_AGGREGATES = f"""
    count() AS calls,
    sumIf({SPEND_EXPR}, NOT ({ERROR_PRED})) AS spend,
    sum({PROMPT_TOKENS_EXPR}) AS input_tokens,
    sum({COMPLETION_TOKENS_EXPR}) AS output_tokens,
    countIf({ERROR_PRED}) AS errors,
    countIf(NOT ({ERROR_PRED}) AND {SPEND_EXPR} = 0) AS unpriced_calls,
    quantile(0.5)(Duration / 1000000) AS p50_ms,
    quantile(0.95)(Duration / 1000000) AS p95_ms
"""

LIST_SELECT = f"""
    SpanId AS request_id,
    Timestamp AS timestamp,
    {MODEL_EXPR} AS model,
    {PROVIDER_EXPR} AS provider,
    '' AS team,
    {STATUS_EXPR} AS status,
    '' AS finish_reason,
    {SPEND_EXPR} AS spend_usd,
    {PROMPT_TOKENS_EXPR} AS prompt_tokens,
    {COMPLETION_TOKENS_EXPR} AS completion_tokens,
    toUInt32(0) AS reasoning_tokens,
    toUInt32(0) AS cache_read_tokens,
    toUInt32(0) AS cache_creation_tokens,
    {TOTAL_TOKENS_EXPR} AS total_tokens,
    {LATENCY_MS_EXPR} AS latency_ms,
    toUInt32(0) AS ttft_ms,
    {TAGS_EXPR} AS tags,
    substring({OUTPUT_TEXT_EXPR}, 1, 240) AS output_preview
"""

DETAIL_SELECT = f"""
    SpanId AS request_id,
    Timestamp AS timestamp,
    {MODEL_EXPR} AS model,
    {PROVIDER_EXPR} AS provider,
    '' AS team,
    {STATUS_EXPR} AS status,
    '' AS finish_reason,
    {SPEND_EXPR} AS spend_usd,
    {PROMPT_TOKENS_EXPR} AS prompt_tokens,
    {COMPLETION_TOKENS_EXPR} AS completion_tokens,
    toUInt32(0) AS reasoning_tokens,
    toUInt32(0) AS cache_read_tokens,
    toUInt32(0) AS cache_creation_tokens,
    {TOTAL_TOKENS_EXPR} AS total_tokens,
    {LATENCY_MS_EXPR} AS latency_ms,
    toUInt32(0) AS ttft_ms,
    {TAGS_EXPR} AS tags,
    substring({OUTPUT_TEXT_EXPR}, 1, 240) AS output_preview,
    toUInt32(0) AS audio_tokens,
    toUInt32(0) AS image_tokens,
    StatusMessage AS error_message,
    toUInt8(0) AS num_retries,
    CAST(NULL AS Nullable(Float32)) AS temperature,
    CAST(NULL AS Nullable(Float32)) AS top_p,
    CAST(NULL AS Nullable(UInt32)) AS max_tokens,
    CAST(NULL AS Nullable(Float32)) AS presence_penalty,
    '' AS metadata,
    {INPUT_MESSAGES_EXPR} AS input_messages,
    {OUTPUT_TEXT_EXPR} AS output_text,
    '' AS reasoning_content,
    '' AS tool_calls
"""

# Map CEL field names → (ClickHouse SQL expression, type).
CEL_FIELD_SQL: dict[str, tuple[str, str]] = {
    "request_id": ("SpanId", "String"),
    "model": (MODEL_EXPR, "String"),
    "provider": (PROVIDER_EXPR, "String"),
    "status": (STATUS_EXPR, "String"),
    "finish_reason": ("''", "String"),
    "spend_usd": (SPEND_EXPR, "Float64"),
    "prompt_tokens": (f"toFloat64({PROMPT_TOKENS_EXPR})", "Float64"),
    "completion_tokens": (f"toFloat64({COMPLETION_TOKENS_EXPR})", "Float64"),
    "total_tokens": (f"toFloat64({TOTAL_TOKENS_EXPR})", "Float64"),
    "latency_ms": (f"toFloat64({LATENCY_MS_EXPR})", "Float64"),
    "ttft_ms": ("toFloat64(0)", "Float64"),
    "num_retries": ("toFloat64(0)", "Float64"),
}
