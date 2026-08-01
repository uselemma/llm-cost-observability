"""SQL expressions mapping aig.otel_traces → CallRow API shape."""
from __future__ import annotations

# Base filter for all dashboard queries.
SERVICE_FILTER = "ServiceName = 'ai-gateway'"

# Attribute helpers — CF docs use gen_ai.model.provider / prompt_json;
# some exporters use gen_ai.provider.name / input.messages. Prefer CF, fall back.
MODEL_EXPR = "SpanAttributes['gen_ai.request.model']"
PROVIDER_EXPR = (
    "if(SpanAttributes['gen_ai.model.provider'] != '', "
    "SpanAttributes['gen_ai.model.provider'], "
    "SpanAttributes['gen_ai.provider.name'])"
)
SPEND_EXPR = "toFloat64OrZero(SpanAttributes['gen_ai.usage.cost'])"
PROMPT_TOKENS_EXPR = "toUInt32OrZero(SpanAttributes['gen_ai.usage.input_tokens'])"
COMPLETION_TOKENS_EXPR = "toUInt32OrZero(SpanAttributes['gen_ai.usage.output_tokens'])"
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
TAGS_EXPR = """arrayFilter(
    x -> x != '',
    [
        if(SpanAttributes['feature'] != '', concat('feature:', SpanAttributes['feature']), ''),
        if(SpanAttributes['prompt'] != '', concat('prompt:', SpanAttributes['prompt']), ''),
        if(SpanAttributes['variant'] != '', concat('variant:', SpanAttributes['variant']), ''),
        if(SpanAttributes['project_id'] != '', concat('project_id:', SpanAttributes['project_id']), '')
    ]
)"""

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
