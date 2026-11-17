-- Remove stored prompt and response text from existing rows without changing cost columns.
--
-- Run only after 005 is applied and the collector change is live (rollout order:
-- 005 -> collector -> 006). Run once per active partition: replace {partition_id}
-- (for example with `sed "s/{partition_id}/20261116/"`), oldest partition first,
-- off-peak, and wait for each mutation to finish (SETTINGS mutations_sync=2).
--
-- ALTER UPDATE SpanAttributes recomputes the MATERIALIZED columns that read it, so the
-- same UPDATE first writes each row's `usage` object to `llm_usage.raw` (which 005 reads,
-- keeping an existing value), then drops the four content keys. A strip-only purge would
-- zero llm_usage. Rows with content but no usage object get an empty `llm_usage.raw`,
-- which 005 treats as absent.
ALTER TABLE aig.otel_traces UPDATE SpanAttributes = mapFilter(
    (k, v) -> k NOT IN (
        'gen_ai.input.messages',
        'gen_ai.output.messages',
        'gen_ai.prompt_json',
        'gen_ai.completion_json'
    ),
    mapUpdate(
        SpanAttributes,
        map('llm_usage.raw', if(
            SpanAttributes['llm_usage.raw'] != '',
            SpanAttributes['llm_usage.raw'],
            JSONExtractRaw(
                if(
                    SpanAttributes['gen_ai.completion_json'] != '',
                    SpanAttributes['gen_ai.completion_json'],
                    SpanAttributes['gen_ai.output.messages']
                ),
                'usage'
            )
        ))
    )
)
IN PARTITION ID '{partition_id}'
WHERE mapContains(SpanAttributes, 'gen_ai.input.messages')
    OR mapContains(SpanAttributes, 'gen_ai.output.messages')
    OR mapContains(SpanAttributes, 'gen_ai.prompt_json')
    OR mapContains(SpanAttributes, 'gen_ai.completion_json')
