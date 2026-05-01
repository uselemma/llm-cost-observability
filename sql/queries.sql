-- Spend by model, current month
SELECT model, sum(spend_usd) AS spend, sum(total_tokens) AS tokens
FROM litellm_logs
WHERE timestamp >= toStartOfMonth(now()) AND status = 'success'
GROUP BY model ORDER BY spend DESC;

-- Cost per prompt template, last 7 days
SELECT
  arrayJoin(arrayFilter(t -> startsWith(t, 'prompt:'), tags)) AS prompt_tag,
  count() AS calls,
  sum(spend_usd) AS spend,
  avg(spend_usd) AS avg_cost
FROM litellm_logs
WHERE timestamp >= now() - INTERVAL 7 DAY
GROUP BY prompt_tag ORDER BY spend DESC;

-- p95 latency by feature, last 24h
SELECT
  arrayJoin(arrayFilter(t -> startsWith(t, 'feature:'), tags)) AS feature,
  quantile(0.95)(latency_ms) AS p95_ms,
  count() AS calls
FROM litellm_logs
WHERE timestamp >= now() - INTERVAL 1 DAY
GROUP BY feature;

-- Spend by customer, current month
SELECT
  arrayJoin(arrayFilter(t -> startsWith(t, 'customer:'), tags)) AS customer,
  sum(spend_usd) AS spend
FROM litellm_logs
WHERE timestamp >= toStartOfMonth(now())
GROUP BY customer ORDER BY spend DESC;

-- Daily spend trend, last 30 days
SELECT toDate(timestamp) AS day, sum(spend_usd) AS spend
FROM litellm_logs
WHERE timestamp >= now() - INTERVAL 30 DAY
GROUP BY day ORDER BY day;

-- Reconciliation: row count for the day (compare against LiteLLM_SpendLogs in Postgres)
SELECT toDate(timestamp) AS day, count() AS rows
FROM litellm_logs
WHERE timestamp >= today() - 1
GROUP BY day;

-- TTFT by model (streaming only)
SELECT model,
       quantile(0.5)(ttft_ms) AS p50,
       quantile(0.95)(ttft_ms) AS p95,
       count() AS streams
FROM litellm_logs
WHERE timestamp >= now() - INTERVAL 1 DAY AND ttft_ms > 0
GROUP BY model ORDER BY p95 DESC;

-- Truncation rate by feature
SELECT
  arrayJoin(arrayFilter(t -> startsWith(t, 'feature:'), tags)) AS feature,
  countIf(finish_reason = 'length') AS truncated,
  count() AS total,
  truncated / total AS truncation_rate
FROM litellm_logs
WHERE timestamp >= now() - INTERVAL 7 DAY AND status = 'success'
GROUP BY feature HAVING total > 50 ORDER BY truncation_rate DESC;

-- Anthropic cache effectiveness
SELECT
  model,
  sum(cache_creation_tokens) AS writes,
  sum(cache_read_tokens) AS reads,
  reads / nullIf(writes, 0) AS read_to_write_ratio,
  sum(spend_usd) AS spend
FROM litellm_logs
WHERE timestamp >= now() - INTERVAL 7 DAY
  AND (cache_creation_tokens > 0 OR cache_read_tokens > 0)
GROUP BY model;
