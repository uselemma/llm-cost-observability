CREATE TABLE IF NOT EXISTS litellm_logs (
    request_id          String,
    timestamp           DateTime64(3),
    model               LowCardinality(String),
    provider            LowCardinality(String),
    api_key_alias       LowCardinality(String),
    team                LowCardinality(String),
    end_user            String,
    prompt_tokens       UInt32,
    completion_tokens   UInt32,
    cache_read_tokens   UInt32,
    total_tokens        UInt32,
    spend_usd           Float64,
    latency_ms          UInt32,
    status              LowCardinality(String),
    tags                Array(String),
    metadata            String,

    input_messages      String CODEC(ZSTD(3)),
    output_text         String CODEC(ZSTD(3)),
    reasoning_content   String CODEC(ZSTD(3))
)
ENGINE = MergeTree
ORDER BY (timestamp, model, team)
PARTITION BY toYYYYMM(timestamp)
TTL toDateTime(timestamp) + INTERVAL 180 DAY;
