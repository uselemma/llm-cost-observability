-- Migration for tables created from the original 001 schema. Adds richer
-- per-call fields. Idempotent — IF NOT EXISTS makes it safe to re-run.
ALTER TABLE litellm_logs
    ADD COLUMN IF NOT EXISTS cache_creation_tokens UInt32 DEFAULT 0 AFTER cache_read_tokens,
    ADD COLUMN IF NOT EXISTS reasoning_tokens UInt32 DEFAULT 0 AFTER cache_creation_tokens,
    ADD COLUMN IF NOT EXISTS audio_tokens UInt32 DEFAULT 0 AFTER reasoning_tokens,
    ADD COLUMN IF NOT EXISTS image_tokens UInt32 DEFAULT 0 AFTER audio_tokens,
    ADD COLUMN IF NOT EXISTS ttft_ms UInt32 DEFAULT 0 AFTER latency_ms,
    ADD COLUMN IF NOT EXISTS finish_reason LowCardinality(String) DEFAULT '' AFTER status,
    ADD COLUMN IF NOT EXISTS error_message String DEFAULT '' CODEC(ZSTD(3)) AFTER finish_reason,
    ADD COLUMN IF NOT EXISTS num_retries UInt8 DEFAULT 0 AFTER error_message,
    ADD COLUMN IF NOT EXISTS temperature Nullable(Float32) AFTER num_retries,
    ADD COLUMN IF NOT EXISTS top_p Nullable(Float32) AFTER temperature,
    ADD COLUMN IF NOT EXISTS max_tokens Nullable(UInt32) AFTER top_p,
    ADD COLUMN IF NOT EXISTS presence_penalty Nullable(Float32) AFTER max_tokens,
    ADD COLUMN IF NOT EXISTS tool_calls String DEFAULT '' CODEC(ZSTD(3));
