"""ClickHouse logical-call projection over Cloudflare and Vercel OTEL roots."""
from __future__ import annotations

SERVICE_FILTER = "ServiceName = 'ai-gateway'"
VERCEL_SOURCE_EXPR = "ResourceAttributes['service.namespace'] = 'vercel'"
VERCEL_ROOT_EXPR = f"({VERCEL_SOURCE_EXPR} AND empty(ParentSpanId))"
ROOT_FILTER = f"({SERVICE_FILTER} AND (NOT ({VERCEL_SOURCE_EXPR}) OR empty(ParentSpanId)))"

# Vercel emits reporting tags as one string attribute. Accept JSON arrays,
# comma-separated values, and the direct call_id used by the infra fixture.
VERCEL_TAG_CALL_ID_EXPR = (
    "extract(SpanAttributes['vercel.ai_gateway.tags'], "
    "'(?:^|[\\\\[\\\\]\", ]+)call:([^\\\\[\\\\]\", ]+)')"
)
RAW_CALL_ID_EXPR = (
    "if(SpanAttributes['call_id'] != '', SpanAttributes['call_id'], "
    f"if({VERCEL_SOURCE_EXPR}, {VERCEL_TAG_CALL_ID_EXPR}, ''))"
)

# Cloudflare currently documents cache status as a response header rather than a
# standard OTEL attribute. Support the known spellings if the exporter or app
# attaches it, but never infer a hit merely because the Vercel root is delayed.
CF_CACHE_STATUS_EXPR = """upper(coalesce(
    nullIf(SpanAttributes['cf-aig-cache-status'], ''),
    nullIf(SpanAttributes['cf.aig.cache.status'], ''),
    nullIf(SpanAttributes['cloudflare.ai_gateway.cache.status'], ''),
    nullIf(SpanAttributes['cache_status'], ''),
    ''
))"""
CF_EXACT_CACHE_HIT_EXPR = f"({CF_CACHE_STATUS_EXPR} = 'HIT')"


def logical_calls_cte(source_where: str = "") -> str:
    """Return the query-only logical-call projection.

    ``source_where`` must contain only trusted, server-authored SQL and should
    bound ``Timestamp`` so ClickHouse can prune the raw table before grouping.
    """
    extra_where = f"\n          AND ({source_where})" if source_where else ""
    return f"""
    WITH root_spans AS (
        SELECT
            *,
            {VERCEL_SOURCE_EXPR} AS is_vercel,
            {RAW_CALL_ID_EXPR} AS call_id,
            if({RAW_CALL_ID_EXPR} != '', {RAW_CALL_ID_EXPR}, SpanId) AS logical_key
        FROM otel_traces
        WHERE {ROOT_FILTER}{extra_where}
    ),
    aggregated_roots AS (
        SELECT
            logical_key,
            max(call_id) AS call_id,
            countIf(NOT is_vercel) AS cloudflare_root_count,
            countIf(is_vercel) AS vercel_root_count,
            argMaxIf(SpanId, Timestamp, NOT is_vercel) AS cloudflare_span_id,
            argMaxIf(SpanId, Timestamp, is_vercel) AS vercel_span_id,
            argMaxIf(TraceId, Timestamp, NOT is_vercel) AS app_trace_id,
            groupUniqArrayIf(TraceId, is_vercel) AS vercel_trace_ids,
            minIf(Timestamp, NOT is_vercel) AS cloudflare_timestamp,
            minIf(Timestamp, is_vercel) AS vercel_timestamp,
            argMaxIf(Duration, Timestamp, NOT is_vercel) AS cloudflare_duration,
            argMaxIf(Duration, Timestamp, is_vercel) AS vercel_duration,
            argMaxIf(StatusCode, Timestamp, NOT is_vercel) AS cloudflare_status_code,
            argMaxIf(StatusCode, Timestamp, is_vercel) AS vercel_status_code,
            argMaxIf(StatusMessage, Timestamp, NOT is_vercel) AS cloudflare_status_message,
            argMaxIf(StatusMessage, Timestamp, is_vercel) AS vercel_status_message,
            argMaxIf(SpanAttributes, Timestamp, NOT is_vercel) AS cloudflare_attrs,
            argMaxIf(SpanAttributes, Timestamp, is_vercel) AS vercel_attrs,
            countIf(NOT is_vercel AND {CF_EXACT_CACHE_HIT_EXPR}) > 0 AS exact_cache_hit,
            sumIf(
                toFloat64OrZero(SpanAttributes['vercel.ai_gateway.cost.total']),
                is_vercel
            ) AS vercel_billed_cost,
            sumIf(
                toFloat64OrZero(SpanAttributes['vercel.ai_gateway.cost.market']),
                is_vercel
            ) AS vercel_market_cost
        FROM root_spans
        GROUP BY logical_key
    ),
    logical_calls AS (
        SELECT
            logical_key AS request_id,
            call_id,
            cloudflare_span_id,
            vercel_span_id,
            app_trace_id,
            vercel_trace_ids,
            if(cloudflare_root_count > 0, cloudflare_timestamp, vercel_timestamp) AS timestamp,
            if(
                vercel_root_count > 0,
                if(
                    vercel_attrs['gen_ai.response.model'] != '',
                    vercel_attrs['gen_ai.response.model'],
                    vercel_attrs['gen_ai.request.model']
                ),
                cloudflare_attrs['gen_ai.request.model']
            ) AS model,
            if(
                vercel_root_count > 0,
                if(
                    vercel_attrs['vercel.ai_gateway.provider'] != '',
                    vercel_attrs['vercel.ai_gateway.provider'],
                    vercel_attrs['gen_ai.provider.name']
                ),
                if(
                    cloudflare_attrs['gen_ai.model.provider'] != '',
                    cloudflare_attrs['gen_ai.model.provider'],
                    cloudflare_attrs['gen_ai.provider.name']
                )
            ) AS provider,
            if(
                if(cloudflare_root_count > 0, cloudflare_status_code, vercel_status_code)
                    = 'STATUS_CODE_ERROR',
                'failure',
                'success'
            ) AS status,
            if(
                vercel_attrs['gen_ai.response.finish_reasons'] != '',
                vercel_attrs['gen_ai.response.finish_reasons'],
                ''
            ) AS finish_reason,
            exact_cache_hit,
            multiIf(
                exact_cache_hit, 'cache_hit',
                cloudflare_root_count > 0 AND vercel_root_count > 0, 'reconciled',
                call_id = '' AND cloudflare_root_count > 0, 'legacy',
                'unreconciled'
            ) AS reconciliation_status,
            toUInt8(
                exact_cache_hit
                OR (cloudflare_root_count > 0 AND vercel_root_count > 0)
                OR (call_id = '' AND cloudflare_root_count > 0)
            ) AS is_complete,
            toUInt8(
                cloudflare_root_count > 0
                AND vercel_root_count = 0
                AND call_id != ''
                AND cloudflare_timestamp <= now64(3) - INTERVAL 2 MINUTE
            ) AS reconciliation_overdue,
            if(
                cloudflare_root_count > 0 AND vercel_root_count > 0,
                toUInt32(abs(dateDiff(
                    'millisecond',
                    cloudflare_timestamp,
                    vercel_timestamp
                ))),
                toUInt32(0)
            ) AS reconciliation_ms,
            toUInt8(
                exact_cache_hit
                OR (cloudflare_root_count > 0 AND vercel_root_count > 0)
                OR (call_id = '' AND cloudflare_root_count > 0)
            ) AS cost_included,
            multiIf(
                exact_cache_hit, 0.,
                cloudflare_root_count > 0 AND vercel_root_count > 0, vercel_billed_cost,
                call_id = '' AND cloudflare_root_count > 0,
                    toFloat64OrZero(cloudflare_attrs['gen_ai.usage.cost']),
                0.
            ) AS spend_usd,
            vercel_billed_cost AS billed_cost_usd,
            vercel_market_cost AS market_cost_usd,
            if(
                vercel_root_count > 0,
                toUInt32OrZero(vercel_attrs['gen_ai.usage.input_tokens']),
                toUInt32OrZero(cloudflare_attrs['gen_ai.usage.input_tokens'])
            ) AS prompt_tokens,
            if(
                vercel_root_count > 0,
                toUInt32OrZero(vercel_attrs['gen_ai.usage.output_tokens']),
                toUInt32OrZero(cloudflare_attrs['gen_ai.usage.output_tokens'])
            ) AS completion_tokens,
            toUInt32OrZero(
                vercel_attrs['gen_ai.usage.reasoning.output_tokens']
            ) AS reasoning_tokens,
            toUInt32OrZero(
                vercel_attrs['gen_ai.usage.cache_read.input_tokens']
            ) AS cache_read_tokens,
            toUInt32OrZero(
                vercel_attrs['gen_ai.usage.cache_creation.input_tokens']
            ) AS cache_creation_tokens,
            toUInt32(intDiv(
                if(cloudflare_root_count > 0, cloudflare_duration, vercel_duration),
                1000000
            )) AS latency_ms,
            toUInt32(round(
                toFloat64OrZero(vercel_attrs['gen_ai.response.time_to_first_chunk']) * 1000
            )) AS ttft_ms,
            toUInt32(intDiv(vercel_duration, 1000000)) AS vercel_latency_ms,
            vercel_attrs['vercel.ai_gateway.generation.id'] AS generation_id,
            vercel_attrs['vercel.ai_gateway.credential.type'] AS credential_type,
            vercel_attrs['vercel.ai_gateway.region'] AS region,
            vercel_attrs['vercel.ai_gateway.zdr.requested'] AS zdr_requested,
            cloudflare_attrs AS SpanAttributes,
            cloudflare_attrs['gen_ai.prompt_json'] AS cf_prompt_json,
            cloudflare_attrs['gen_ai.completion_json'] AS cf_completion_json,
            if(
                cloudflare_attrs['gen_ai.prompt_json'] != '',
                cloudflare_attrs['gen_ai.prompt_json'],
                cloudflare_attrs['gen_ai.input.messages']
            ) AS input_messages,
            if(
                cloudflare_attrs['gen_ai.completion_json'] != '',
                cloudflare_attrs['gen_ai.completion_json'],
                cloudflare_attrs['gen_ai.output.messages']
            ) AS output_text,
            if(
                cloudflare_root_count > 0,
                cloudflare_status_message,
                vercel_status_message
            ) AS error_message,
            arrayFilter(
                x -> x != '',
                [
                    if(cloudflare_attrs['feature'] != '',
                        concat('feature:', cloudflare_attrs['feature']), ''),
                    if(cloudflare_attrs['prompt'] != '',
                        concat('prompt:', cloudflare_attrs['prompt']), ''),
                    if(cloudflare_attrs['project_id'] != '',
                        concat('project_id:', cloudflare_attrs['project_id']), ''),
                    if(cloudflare_attrs['experiment'] != '',
                        concat('experiment:', cloudflare_attrs['experiment']), ''),
                    if(cloudflare_attrs['variant'] != '',
                        concat('variant:', cloudflare_attrs['variant']), ''),
                    if(JSONExtractString(cloudflare_attrs['experiment_variant'], 1) != '',
                        concat(
                            'experiment:',
                            JSONExtractString(cloudflare_attrs['experiment_variant'], 1)
                        ), ''),
                    if(JSONExtractString(cloudflare_attrs['experiment_variant'], 2) != '',
                        concat(
                            'variant:',
                            JSONExtractString(cloudflare_attrs['experiment_variant'], 2)
                        ), '')
                ]
            ) AS tags
        FROM aggregated_roots
    )
    """


MODEL_EXPR = "model"
PROVIDER_EXPR = "provider"
SPEND_EXPR = "spend_usd"
PROMPT_TOKENS_EXPR = "prompt_tokens"
COMPLETION_TOKENS_EXPR = "completion_tokens"
TOTAL_TOKENS_EXPR = (
    "(prompt_tokens + completion_tokens + reasoning_tokens)"
)
LATENCY_MS_EXPR = "latency_ms"
STATUS_EXPR = "status"
INPUT_MESSAGES_EXPR = "input_messages"
OUTPUT_TEXT_EXPR = "output_text"
TAGS_EXPR = "tags"

LIST_SELECT = f"""
    request_id,
    timestamp,
    {MODEL_EXPR} AS model,
    {PROVIDER_EXPR} AS provider,
    '' AS team,
    {STATUS_EXPR} AS status,
    '' AS finish_reason,
    {SPEND_EXPR} AS spend_usd,
    {PROMPT_TOKENS_EXPR} AS prompt_tokens,
    {COMPLETION_TOKENS_EXPR} AS completion_tokens,
    reasoning_tokens,
    cache_read_tokens,
    cache_creation_tokens,
    {TOTAL_TOKENS_EXPR} AS total_tokens,
    {LATENCY_MS_EXPR} AS latency_ms,
    ttft_ms,
    {TAGS_EXPR} AS tags,
    substring({OUTPUT_TEXT_EXPR}, 1, 240) AS output_preview,
    reconciliation_status,
    is_complete,
    reconciliation_overdue,
    reconciliation_ms,
    cost_included,
    exact_cache_hit
"""

DETAIL_SELECT = f"""
    request_id,
    timestamp,
    {MODEL_EXPR} AS model,
    {PROVIDER_EXPR} AS provider,
    '' AS team,
    {STATUS_EXPR} AS status,
    '' AS finish_reason,
    {SPEND_EXPR} AS spend_usd,
    {PROMPT_TOKENS_EXPR} AS prompt_tokens,
    {COMPLETION_TOKENS_EXPR} AS completion_tokens,
    reasoning_tokens,
    cache_read_tokens,
    cache_creation_tokens,
    {TOTAL_TOKENS_EXPR} AS total_tokens,
    {LATENCY_MS_EXPR} AS latency_ms,
    ttft_ms,
    {TAGS_EXPR} AS tags,
    substring({OUTPUT_TEXT_EXPR}, 1, 240) AS output_preview,
    toUInt32(0) AS audio_tokens,
    toUInt32(0) AS image_tokens,
    error_message,
    if(length(vercel_trace_ids) > 0, length(vercel_trace_ids) - 1, 0) AS num_retries,
    CAST(NULL AS Nullable(Float32)) AS temperature,
    CAST(NULL AS Nullable(Float32)) AS top_p,
    CAST(NULL AS Nullable(UInt32)) AS max_tokens,
    CAST(NULL AS Nullable(Float32)) AS presence_penalty,
    toJSONString(SpanAttributes) AS metadata,
    {INPUT_MESSAGES_EXPR} AS input_messages,
    {OUTPUT_TEXT_EXPR} AS output_text,
    '' AS reasoning_content,
    '' AS tool_calls,
    call_id,
    cloudflare_span_id,
    vercel_span_id,
    app_trace_id,
    vercel_trace_ids,
    reconciliation_status,
    is_complete,
    reconciliation_overdue,
    reconciliation_ms,
    cost_included,
    exact_cache_hit,
    billed_cost_usd,
    market_cost_usd,
    vercel_latency_ms,
    generation_id,
    credential_type,
    region,
    zdr_requested
"""

ATTEMPTS_SELECT = """
    SpanId AS span_id,
    ParentSpanId AS parent_span_id,
    SpanName AS name,
    SpanKind AS kind,
    if(StatusCode = 'STATUS_CODE_ERROR', 'failure', 'success') AS status,
    StatusMessage AS error_message,
    toUInt32(intDiv(Duration, 1000000)) AS latency_ms,
    SpanAttributes['gen_ai.request.model'] AS model,
    if(
        SpanAttributes['vercel.ai_gateway.provider'] != '',
        SpanAttributes['vercel.ai_gateway.provider'],
        SpanAttributes['gen_ai.provider.name']
    ) AS provider,
    toUInt32OrZero(SpanAttributes['vercel.ai_gateway.model_attempt.index']) AS model_attempt_index,
    toUInt32OrZero(SpanAttributes['vercel.ai_gateway.attempt.number']) AS attempt_number,
    SpanAttributes['vercel.ai_gateway.attempt.id'] AS attempt_id,
    SpanAttributes['vercel.ai_gateway.attempt.success'] AS attempt_success,
    SpanAttributes['vercel.ai_gateway.attempt.provider_timeout'] AS provider_timeout,
    toUInt32OrZero(
        SpanAttributes['vercel.ai_gateway.attempt.configured_timeout_ms']
    ) AS configured_timeout_ms,
    SpanAttributes['vercel.ai_gateway.credential.type'] AS credential_type,
    SpanAttributes['vercel.ai_gateway.region'] AS region
"""

# Map CEL field names → (ClickHouse SQL expression, type).
CEL_FIELD_SQL: dict[str, tuple[str, str]] = {
    "request_id": ("request_id", "String"),
    "model": (MODEL_EXPR, "String"),
    "provider": (PROVIDER_EXPR, "String"),
    "status": (STATUS_EXPR, "String"),
    "finish_reason": ("''", "String"),
    "spend_usd": (SPEND_EXPR, "Float64"),
    "prompt_tokens": (f"toFloat64({PROMPT_TOKENS_EXPR})", "Float64"),
    "completion_tokens": (f"toFloat64({COMPLETION_TOKENS_EXPR})", "Float64"),
    "total_tokens": (f"toFloat64({TOTAL_TOKENS_EXPR})", "Float64"),
    "latency_ms": (f"toFloat64({LATENCY_MS_EXPR})", "Float64"),
    "ttft_ms": ("toFloat64(ttft_ms)", "Float64"),
    "num_retries": (
        "toFloat64(if(length(vercel_trace_ids) > 0, length(vercel_trace_ids) - 1, 0))",
        "Float64",
    ),
    "reconciliation_ms": ("toFloat64(reconciliation_ms)", "Float64"),
    "reconciliation_status": ("reconciliation_status", "String"),
}
