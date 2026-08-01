-- Analytics against Cloudflare AI Gateway OTEL spans (aig.otel_traces).
-- Always filter ServiceName = 'ai-gateway' and bound Timestamp.

-- Spend by model, current month
SELECT
  SpanAttributes['gen_ai.request.model'] AS model,
  sum(toFloat64OrZero(SpanAttributes['gen_ai.usage.cost'])) AS spend,
  sum(toUInt32OrZero(SpanAttributes['gen_ai.usage.input_tokens'])
    + toUInt32OrZero(SpanAttributes['gen_ai.usage.output_tokens'])) AS tokens
FROM otel_traces
WHERE ServiceName = 'ai-gateway'
  AND Timestamp >= toStartOfMonth(now())
  AND StatusCode != 'STATUS_CODE_ERROR'
GROUP BY model
ORDER BY spend DESC;

-- Cost per prompt template, last 7 days
SELECT
  concat('prompt:', SpanAttributes['prompt']) AS prompt_tag,
  count() AS calls,
  sum(toFloat64OrZero(SpanAttributes['gen_ai.usage.cost'])) AS spend,
  avg(toFloat64OrZero(SpanAttributes['gen_ai.usage.cost'])) AS avg_cost
FROM otel_traces
WHERE ServiceName = 'ai-gateway'
  AND Timestamp >= now() - INTERVAL 7 DAY
  AND SpanAttributes['prompt'] != ''
GROUP BY prompt_tag
ORDER BY spend DESC;

-- p95 latency by feature, last 24h
SELECT
  concat('feature:', SpanAttributes['feature']) AS feature,
  quantile(0.95)(intDiv(Duration, 1000000)) AS p95_ms,
  count() AS calls
FROM otel_traces
WHERE ServiceName = 'ai-gateway'
  AND Timestamp >= now() - INTERVAL 1 DAY
  AND SpanAttributes['feature'] != ''
GROUP BY feature
ORDER BY p95_ms DESC;

-- Spend by project_id, current month
SELECT
  SpanAttributes['project_id'] AS project_id,
  sum(toFloat64OrZero(SpanAttributes['gen_ai.usage.cost'])) AS spend
FROM otel_traces
WHERE ServiceName = 'ai-gateway'
  AND Timestamp >= toStartOfMonth(now())
  AND SpanAttributes['project_id'] != ''
GROUP BY project_id
ORDER BY spend DESC;

-- Daily spend trend, last 30 days
SELECT
  toDate(Timestamp) AS day,
  sum(toFloat64OrZero(SpanAttributes['gen_ai.usage.cost'])) AS spend
FROM otel_traces
WHERE ServiceName = 'ai-gateway'
  AND Timestamp >= now() - INTERVAL 30 DAY
GROUP BY day
ORDER BY day;

-- Error rate by model
SELECT
  SpanAttributes['gen_ai.request.model'] AS model,
  countIf(StatusCode = 'STATUS_CODE_ERROR') AS failures,
  count() AS total,
  failures / total AS failure_rate
FROM otel_traces
WHERE ServiceName = 'ai-gateway'
  AND Timestamp >= now() - INTERVAL 1 DAY
GROUP BY model
HAVING total > 100
ORDER BY failure_rate DESC;

-- Cost of one feature, by model
SELECT
  SpanAttributes['gen_ai.request.model'] AS model,
  count() AS calls,
  sum(toFloat64OrZero(SpanAttributes['gen_ai.usage.cost'])) AS spend
FROM otel_traces
WHERE ServiceName = 'ai-gateway'
  AND Timestamp >= now() - INTERVAL 30 DAY
  AND SpanAttributes['feature'] = 'summarization'
  AND StatusCode != 'STATUS_CODE_ERROR'
GROUP BY model
ORDER BY spend DESC;

-- Inspect a specific span
SELECT
  Timestamp,
  SpanId,
  SpanAttributes['gen_ai.request.model'] AS model,
  StatusCode,
  intDiv(Duration, 1000000) AS latency_ms,
  toFloat64OrZero(SpanAttributes['gen_ai.usage.cost']) AS spend_usd,
  SpanAttributes['feature'] AS feature,
  SpanAttributes['prompt'] AS prompt,
  SpanAttributes['gen_ai.prompt_json'] AS input_messages,
  SpanAttributes['gen_ai.completion_json'] AS output_text
FROM otel_traces
WHERE ServiceName = 'ai-gateway'
  AND SpanId = '...'
LIMIT 1;
