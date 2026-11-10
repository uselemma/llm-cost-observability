-- Pre-extracted hot fields so dashboard queries never read the SpanAttributes map
-- (which holds prompt/completion bodies). New rows fill it on insert.
ALTER TABLE aig.otel_traces ADD COLUMN IF NOT EXISTS llm_meta Tuple(model LowCardinality(String), provider LowCardinality(String), feature LowCardinality(String), prompt LowCardinality(String), project_id LowCardinality(String), variant LowCardinality(String), cost Float64, input_tokens UInt32, output_tokens UInt32) MATERIALIZED tuple(SpanAttributes['gen_ai.request.model'], if(SpanAttributes['gen_ai.model.provider'] != '', SpanAttributes['gen_ai.model.provider'], SpanAttributes['gen_ai.provider.name']), SpanAttributes['feature'], SpanAttributes['prompt'], SpanAttributes['project_id'], SpanAttributes['experiment_variant'], toFloat64OrZero(SpanAttributes['gen_ai.usage.cost']), toUInt32OrZero(SpanAttributes['gen_ai.usage.input_tokens']), toUInt32OrZero(SpanAttributes['gen_ai.usage.output_tokens']))

-- Backfill existing rows (background mutation; reads the table once):
-- ALTER TABLE aig.otel_traces MATERIALIZE COLUMN llm_meta;
