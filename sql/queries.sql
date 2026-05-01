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
