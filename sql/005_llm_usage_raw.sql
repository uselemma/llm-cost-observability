-- Point llm_usage at the compact `llm_usage.raw` attribute (the response's `usage` object),
-- which the collector's transform/strip_llm_content processor writes before it drops the
-- prompt and response text. Rows without it (written before the collector change, or
-- before sql/006 ran) fall back to the old extraction from completion_json/output.messages.
-- The parsing of the usage object is unchanged from 004.
--
-- Rollout order: 005 -> collector change live -> 006. Run 005 BEFORE the collector ships:
-- once content is dropped, the old expression would compute zeros for new rows.
-- MODIFY COLUMN ... MATERIALIZED is metadata-only: no mutation runs and stored values are kept.
ALTER TABLE aig.otel_traces MODIFY COLUMN llm_usage Tuple(cached UInt32, cache_write UInt32, reported_cost Float64) MATERIALIZED arrayMap(u -> (toUInt32(greatest(JSONExtractUInt(u, 'input_tokens_details', 'cached_tokens'), JSONExtractUInt(u, 'prompt_tokens_details', 'cached_tokens'))), toUInt32(greatest(JSONExtractUInt(u, 'input_tokens_details', 'cache_write_tokens'), JSONExtractUInt(u, 'prompt_tokens_details', 'cache_write_tokens'), JSONExtractUInt(u, 'cache_creation_input_tokens'))), JSONExtractFloat(u, 'cost')), [if(SpanAttributes['llm_usage.raw'] != '', SpanAttributes['llm_usage.raw'], JSONExtractRaw(if(SpanAttributes['gen_ai.completion_json'] != '', SpanAttributes['gen_ai.completion_json'], SpanAttributes['gen_ai.output.messages']), 'usage'))])[1]
