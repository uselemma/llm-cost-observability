-- Cached-token counts and the body-reported cost, parsed once from the response body's
-- `usage` block, so cost queries never read the body-heavy SpanAttributes map.
-- New rows fill it on insert. Needed for cache-aware costing (see app/queries.py SPEND_EXPR).
-- Handles both Responses-API (input_tokens_details) and chat-completions (prompt_tokens_details)
-- shapes, plus Anthropic-style cache_creation_input_tokens.
ALTER TABLE aig.otel_traces ADD COLUMN IF NOT EXISTS llm_usage Tuple(cached UInt32, cache_write UInt32, reported_cost Float64) MATERIALIZED arrayMap(u -> (toUInt32(greatest(JSONExtractUInt(u, 'input_tokens_details', 'cached_tokens'), JSONExtractUInt(u, 'prompt_tokens_details', 'cached_tokens'))), toUInt32(greatest(JSONExtractUInt(u, 'input_tokens_details', 'cache_write_tokens'), JSONExtractUInt(u, 'prompt_tokens_details', 'cache_write_tokens'), JSONExtractUInt(u, 'cache_creation_input_tokens'))), JSONExtractFloat(u, 'cost')), [JSONExtractRaw(if(SpanAttributes['gen_ai.completion_json'] != '', SpanAttributes['gen_ai.completion_json'], SpanAttributes['gen_ai.output.messages']), 'usage')])[1]

-- Backfill existing rows: a background mutation that reads the whole table once (~185 GiB).
-- It slows the service while it runs (the llm_meta backfill took ~35 min), so run it off-peak.
-- ALTER TABLE aig.otel_traces MATERIALIZE COLUMN llm_usage;
