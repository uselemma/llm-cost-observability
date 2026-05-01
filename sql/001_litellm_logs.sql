CREATE TABLE IF NOT EXISTS litellm_logs (
    request_id          String,
    timestamp           DateTime64(3),
    model               LowCardinality(String),
    provider            LowCardinality(String),
    api_key_alias       LowCardinality(String),
    team                LowCardinality(String),
    end_user            String,

    -- Token usage
    prompt_tokens           UInt32,
    completion_tokens       UInt32,
    cache_read_tokens       UInt32,
    cache_creation_tokens   UInt32,
    reasoning_tokens        UInt32,
    audio_tokens            UInt32,
    image_tokens            UInt32,
    total_tokens            UInt32,

    -- Cost & timing
    spend_usd           Float64,
    latency_ms          UInt32,
    ttft_ms             UInt32,            -- 0 for non-streaming

    -- Outcome
    status              LowCardinality(String),
    finish_reason       LowCardinality(String),
    error_message       String CODEC(ZSTD(3)),
    num_retries         UInt8,

    -- Request params (for debugging cost regressions)
    temperature         Nullable(Float32),
    top_p               Nullable(Float32),
    max_tokens          Nullable(UInt32),
    presence_penalty    Nullable(Float32),

    -- Attribution
    tags                Array(String),
    metadata            String,             -- raw JSON for fields we don't promote

    -- Bodies. Compressed heavily; same retention as metrics (180d).
    input_messages      String CODEC(ZSTD(3)),
    output_text         String CODEC(ZSTD(3)),
    reasoning_content   String CODEC(ZSTD(3)),
    tool_calls          String CODEC(ZSTD(3))
)
ENGINE = MergeTree
ORDER BY (timestamp, model, team)
PARTITION BY toYYYYMM(timestamp)
TTL toDateTime(timestamp) + INTERVAL 180 DAY;
