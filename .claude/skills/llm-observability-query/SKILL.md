---
name: llm-observability-query
description: Use when the user asks a cost, usage, latency, or attribution question about LLM calls — e.g. "what did feature X cost last month", "spend by model", "p95 latency for our summarization endpoint", "which prompt version is most expensive", "how much did customer Y spend on Claude". Also use for debugging a specific past LLM call by request ID, or for offline evals against historical traffic. Queries the `litellm_logs` table in ClickHouse Cloud via the ClickHouse MCP.
---

# Querying LLM cost & usage from ClickHouse

Every LLM call our services make lands in the `litellm_logs` table in
ClickHouse Cloud. Use the ClickHouse MCP's `run_select_query` tool to answer
cost, usage, latency, and attribution questions. Schema and example queries
live in the project repo: https://github.com/uselemma/llm-cost-observability.

## Connecting

The ClickHouse MCP is configured against our Cloud service. Confirm the
service exists with `get_services_list`, then use `run_select_query` with the
`service_id` to run any of the queries below.

If the user hasn't specified, default to the **prod** service / database. Ask
which env if the question is ambiguous (e.g. "what did dev spend on Claude?"
clearly means dev).

## Schema (`litellm_logs`)

### Identity & attribution
| Column | Type | Notes |
|---|---|---|
| `request_id` | String | LiteLLM call ID, unique per request. |
| `timestamp` | DateTime64(3) | Always filter on this — the table is partitioned by month. |
| `model` | LowCardinality(String) | The model the proxy resolved, e.g. `vercel_ai_gateway/anthropic/claude-opus-4.6`. |
| `provider` | LowCardinality(String) | Underlying provider (anthropic, openai, ...). |
| `team` | LowCardinality(String) | `dev` or `prod`. Stamped from the API key. |
| `api_key_alias` | LowCardinality(String) | Key alias if set; usually empty in our setup. |
| `end_user` | String | Optional `metadata.user` from the request. |
| `tags` | Array(String) | Includes `env:<dev|prod>`, `feature:<name>`, `prompt:<name-vN>`, optionally `customer:`, `experiment:`. |
| `metadata` | String | Raw JSON for fields not promoted to columns. Use `JSONExtract*`. |

### Token usage
| Column | Type | Notes |
|---|---|---|
| `prompt_tokens` / `completion_tokens` / `total_tokens` | UInt32 | |
| `cache_read_tokens` | UInt32 | Anthropic prompt-cache read side. |
| `cache_creation_tokens` | UInt32 | Anthropic prompt-cache write side (more expensive than uncached input). |
| `reasoning_tokens` | UInt32 | Extended-thinking / o-series reasoning tokens. Separate billed bucket. |
| `audio_tokens` / `image_tokens` | UInt32 | Multimodal breakdown when applicable. |

### Cost & timing
| Column | Type | Notes |
|---|---|---|
| `spend_usd` | Float64 | LiteLLM's computed cost. **List price**, not what Vercel actually billed. |
| `latency_ms` | UInt32 | Wall-clock duration the proxy observed. |
| `ttft_ms` | UInt32 | Time-to-first-token. **0 for non-streaming** — filter `WHERE ttft_ms > 0` for stream-only analysis. |

### Outcome
| Column | Type | Notes |
|---|---|---|
| `status` | LowCardinality(String) | `success` or `failure`. Filter to `'success'` for cost rollups. |
| `finish_reason` | LowCardinality(String) | `stop` / `length` / `tool_calls` / `content_filter`. `length` means truncated at `max_tokens`. |
| `error_message` | String (ZSTD) | Populated only when `status='failure'`. Truncated to 4000 chars. |
| `num_retries` | UInt8 | If LiteLLM retried before succeeding, this is the count of *prior* failed attempts. Each one is its own row too. |

### Request params (debugging cost regressions)
| Column | Type | Notes |
|---|---|---|
| `temperature` / `top_p` / `presence_penalty` | Nullable(Float32) | Null = caller didn't set it. |
| `max_tokens` | Nullable(UInt32) | Null = caller didn't set it. Sudden jumps here usually explain "why did this prompt cost 3x?". |

### Bodies (use sparingly — heavy columns)
| Column | Type | Notes |
|---|---|---|
| `input_messages` | String (ZSTD) | Full request messages, JSON-encoded. |
| `output_text` | String (ZSTD) | Assistant response content. |
| `reasoning_content` | String (ZSTD) | Extended-thinking text (Anthropic / o-series). |
| `tool_calls` | String (ZSTD) | Tool call array if the response invoked tools, JSON-encoded. |

Retention: 180 days. Older data is gone.

## Query patterns

Always:

- **Bound by `timestamp`.** A query without a time bound scans every partition.
- **Use `has(tags, 'key:value')`** to filter by tag, not `arrayJoin` (which
  multiplies rows).
- **Use `arrayJoin(arrayFilter(t -> startsWith(t, 'feature:'), tags))`** to
  group by tag prefix.

### Spend by model, current month

```sql
SELECT model, sum(spend_usd) AS spend, sum(total_tokens) AS tokens
FROM litellm_logs
WHERE timestamp >= toStartOfMonth(now()) AND status = 'success'
GROUP BY model ORDER BY spend DESC;
```

### Cost per prompt template, last 7 days

```sql
SELECT
  arrayJoin(arrayFilter(t -> startsWith(t, 'prompt:'), tags)) AS prompt_tag,
  count() AS calls,
  sum(spend_usd) AS spend,
  avg(spend_usd) AS avg_cost
FROM litellm_logs
WHERE timestamp >= now() - INTERVAL 7 DAY
GROUP BY prompt_tag ORDER BY spend DESC;
```

### Cost of one specific feature, broken down by model

```sql
SELECT model, count() AS calls, sum(spend_usd) AS spend
FROM litellm_logs
WHERE timestamp >= now() - INTERVAL 30 DAY
  AND has(tags, 'feature:summarization')
  AND status = 'success'
GROUP BY model ORDER BY spend DESC;
```

### p95 latency by feature, last 24h

```sql
SELECT
  arrayJoin(arrayFilter(t -> startsWith(t, 'feature:'), tags)) AS feature,
  quantile(0.95)(latency_ms) AS p95_ms,
  count() AS calls
FROM litellm_logs
WHERE timestamp >= now() - INTERVAL 1 DAY
GROUP BY feature
ORDER BY p95_ms DESC;
```

### A/B comparison: two prompt versions

```sql
SELECT
  arrayJoin(arrayFilter(t -> t IN ('prompt:summarize-v2', 'prompt:summarize-v3'), tags)) AS prompt,
  count() AS calls,
  sum(spend_usd) AS spend,
  avg(spend_usd) AS avg_cost,
  avg(completion_tokens) AS avg_completion_tokens
FROM litellm_logs
WHERE timestamp >= now() - INTERVAL 14 DAY
  AND status = 'success'
GROUP BY prompt;
```

### Per-customer spend, current month

```sql
SELECT
  arrayJoin(arrayFilter(t -> startsWith(t, 'customer:'), tags)) AS customer,
  sum(spend_usd) AS spend,
  count() AS calls
FROM litellm_logs
WHERE timestamp >= toStartOfMonth(now()) AND status = 'success'
GROUP BY customer ORDER BY spend DESC LIMIT 50;
```

### Daily spend trend

```sql
SELECT toDate(timestamp) AS day, sum(spend_usd) AS spend
FROM litellm_logs
WHERE timestamp >= now() - INTERVAL 30 DAY AND status = 'success'
GROUP BY day ORDER BY day;
```

### Error rate by model

```sql
SELECT
  model,
  countIf(status = 'failure') AS failures,
  count() AS total,
  failures / total AS failure_rate
FROM litellm_logs
WHERE timestamp >= now() - INTERVAL 1 DAY
GROUP BY model
HAVING total > 100
ORDER BY failure_rate DESC;
```

### TTFT by model (streams only)

```sql
SELECT model,
       quantile(0.5)(ttft_ms) AS p50,
       quantile(0.95)(ttft_ms) AS p95,
       count() AS streams
FROM litellm_logs
WHERE timestamp >= now() - INTERVAL 1 DAY
  AND ttft_ms > 0
GROUP BY model ORDER BY p95 DESC;
```

### Truncation rate by feature (hit `max_tokens`)

```sql
SELECT
  arrayJoin(arrayFilter(t -> startsWith(t, 'feature:'), tags)) AS feature,
  countIf(finish_reason = 'length') AS truncated,
  count() AS total,
  truncated / total AS truncation_rate
FROM litellm_logs
WHERE timestamp >= now() - INTERVAL 7 DAY
  AND status = 'success'
GROUP BY feature
HAVING total > 50
ORDER BY truncation_rate DESC;
```

### Failure breakdown by error

```sql
SELECT
  model,
  substring(error_message, 1, 100) AS err,
  count() AS failures
FROM litellm_logs
WHERE timestamp >= now() - INTERVAL 1 DAY
  AND status = 'failure'
GROUP BY model, err
ORDER BY failures DESC LIMIT 50;
```

### Anthropic cache effectiveness

```sql
SELECT
  model,
  sum(cache_creation_tokens) AS writes,
  sum(cache_read_tokens) AS reads,
  -- Reads are ~10% of input price; writes are ~125%. Effective only when reads >> writes.
  reads / nullIf(writes, 0) AS read_to_write_ratio,
  sum(spend_usd) AS spend
FROM litellm_logs
WHERE timestamp >= now() - INTERVAL 7 DAY
  AND (cache_creation_tokens > 0 OR cache_read_tokens > 0)
GROUP BY model;
```

### Retry tax

```sql
SELECT
  model,
  countIf(num_retries > 0) AS calls_that_retried,
  count() AS total_calls,
  sum(num_retries) AS prior_failed_attempts
FROM litellm_logs
WHERE timestamp >= now() - INTERVAL 7 DAY
GROUP BY model ORDER BY prior_failed_attempts DESC;
```

### "Why did this prompt suddenly cost more?"

Compare request params week-over-week for one prompt:

```sql
SELECT
  toStartOfWeek(timestamp) AS week,
  avg(max_tokens) AS avg_max_tokens,
  avg(completion_tokens) AS avg_completion,
  avg(spend_usd) AS avg_cost
FROM litellm_logs
WHERE timestamp >= now() - INTERVAL 30 DAY
  AND has(tags, 'prompt:summarize-v3')
GROUP BY week ORDER BY week;
```

### Tool-call usage

```sql
SELECT
  arrayJoin(arrayFilter(t -> startsWith(t, 'feature:'), tags)) AS feature,
  countIf(tool_calls != '') AS tool_calls,
  count() AS total
FROM litellm_logs
WHERE timestamp >= now() - INTERVAL 1 DAY
GROUP BY feature
HAVING tool_calls > 0;
```

### Inspect a specific call (debugging or eval seed)

```sql
SELECT timestamp, model, status, latency_ms, spend_usd, tags,
       input_messages, output_text, reasoning_content
FROM litellm_logs
WHERE request_id = '...'
LIMIT 1;
```

The body columns are big — only select them when needed.

### Cache hit rate

```sql
SELECT
  model,
  sum(cache_read_tokens) AS cached,
  sum(prompt_tokens) AS total_prompt,
  cached / total_prompt AS cache_ratio
FROM litellm_logs
WHERE timestamp >= now() - INTERVAL 7 DAY
  AND prompt_tokens > 0
GROUP BY model ORDER BY cache_ratio DESC;
```

## Caveats

- **`spend_usd` is list price**, not your Vercel invoice. There may be a
  consistent delta. Use it for relative comparisons (which feature/model is
  most expensive); use the Vercel invoice for absolute monthly totals.
- **Failures still consume tokens** sometimes. Filter `status = 'success'` for
  cost rollups; don't filter for usage analysis where you care about all
  attempts.
- **180-day retention.** "Last quarter" works; "last year" doesn't.
- **`tags` is unordered.** Don't rely on positional access; always use
  `has()` or `arrayFilter`.
- **Don't `SELECT *`** for body queries. Pulling `input_messages` and
  `output_text` for thousands of rows will be slow.

## Reporting results

When the user asks "what did X cost," report:

1. The number with units (`$1,247.32`).
2. The time window (`last 30 days`, `current month so far`).
3. The breakdown they're likely to want next (by model? by prompt version?).

Avoid burying the headline in a table. Lead with the answer, then offer the
breakdown.
