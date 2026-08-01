---
name: llm-observability-query
description: Use when the user asks a cost, usage, latency, or attribution question about LLM calls — e.g. "what did feature X cost last month", "spend by model", "p95 latency for summarization", "which prompt version is most expensive". Also for debugging a past call by span ID. Queries aig.otel_traces (Cloudflare AI Gateway OTEL) in ClickHouse — not litellm_logs.
---

# Querying LLM cost & usage from ClickHouse (AI Gateway OTEL)

Every LLM call through Cloudflare AI Gateway lands in **`aig.otel_traces`**
(`ServiceName = 'ai-gateway'`). Schema/examples live in
https://github.com/uselemma/llm-cost-observability (`sql/queries.sql`).

The old `litellm_logs` table is retired (ENG-408). Do not query it.

## Connecting

Use ClickHouse credentials for the **LLM** cluster / database `aig`
(`LLM_CLICKHOUSE_*` in AWS Secrets Manager), not the product analytics CH.

If a ClickHouse MCP is configured, run selects against that service with
`database = aig` (or fully qualify `aig.otel_traces`).

## Schema (`otel_traces` — relevant columns)

| Column | Notes |
|---|---|
| `Timestamp` | Always filter on this. |
| `SpanId` | Unique per gateway request span (= dashboard `request_id`). |
| `TraceId` | Trace id (may link to app traces via `cf-aig-otel-*` headers). |
| `Duration` | Nanoseconds. Use `intDiv(Duration, 1000000)` for ms. |
| `ServiceName` | Filter `= 'ai-gateway'`. |
| `StatusCode` | `STATUS_CODE_ERROR` = failure; otherwise treat as success. |
| `StatusMessage` | Error detail when failed. |
| `SpanAttributes` | `Map` of string attrs (GenAI + `cf-aig-metadata`). |

### Important `SpanAttributes` keys

| Key | Notes |
|---|---|
| `gen_ai.request.model` | Model requested |
| `gen_ai.model.provider` | Provider (CF docs); some spans may use `gen_ai.provider.name` |
| `gen_ai.usage.input_tokens` / `output_tokens` | Token counts (string-encoded in the map) |
| `gen_ai.usage.cost` | Estimated USD cost |
| `gen_ai.prompt_json` / `gen_ai.completion_json` | Request / response bodies |
| `feature`, `prompt`, `variant`, `project_id` | From `cf-aig-metadata` |

Cast numeric attrs with `toFloat64OrZero(...)` / `toUInt32OrZero(...)`.

## Query patterns

Always:

- **Bound by `Timestamp`.**
- **Filter `ServiceName = 'ai-gateway'`.**
- Prefer `SpanAttributes['feature'] = '…'` over reconstructing tag arrays.

### Spend by model, current month

```sql
SELECT
  SpanAttributes['gen_ai.request.model'] AS model,
  sum(toFloat64OrZero(SpanAttributes['gen_ai.usage.cost'])) AS spend,
  count() AS calls
FROM otel_traces
WHERE ServiceName = 'ai-gateway'
  AND Timestamp >= toStartOfMonth(now())
  AND StatusCode != 'STATUS_CODE_ERROR'
GROUP BY model
ORDER BY spend DESC;
```

### Cost per prompt, last 7 days

```sql
SELECT
  SpanAttributes['prompt'] AS prompt,
  count() AS calls,
  sum(toFloat64OrZero(SpanAttributes['gen_ai.usage.cost'])) AS spend,
  avg(toFloat64OrZero(SpanAttributes['gen_ai.usage.cost'])) AS avg_cost
FROM otel_traces
WHERE ServiceName = 'ai-gateway'
  AND Timestamp >= now() - INTERVAL 7 DAY
  AND SpanAttributes['prompt'] != ''
GROUP BY prompt
ORDER BY spend DESC;
```

### p95 latency by feature, last 24h

```sql
SELECT
  SpanAttributes['feature'] AS feature,
  quantile(0.95)(intDiv(Duration, 1000000)) AS p95_ms,
  count() AS calls
FROM otel_traces
WHERE ServiceName = 'ai-gateway'
  AND Timestamp >= now() - INTERVAL 1 DAY
  AND SpanAttributes['feature'] != ''
GROUP BY feature
ORDER BY p95_ms DESC;
```

### One feature, by model

```sql
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
```

### Daily spend trend

```sql
SELECT toDate(Timestamp) AS day,
       sum(toFloat64OrZero(SpanAttributes['gen_ai.usage.cost'])) AS spend
FROM otel_traces
WHERE ServiceName = 'ai-gateway'
  AND Timestamp >= now() - INTERVAL 30 DAY
  AND StatusCode != 'STATUS_CODE_ERROR'
GROUP BY day
ORDER BY day;
```

### Error rate by model

```sql
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
```

### Inspect a span (dashboard detail / eval seed)

```sql
SELECT
  Timestamp, SpanId, StatusCode,
  intDiv(Duration, 1000000) AS latency_ms,
  toFloat64OrZero(SpanAttributes['gen_ai.usage.cost']) AS spend_usd,
  SpanAttributes['feature'], SpanAttributes['prompt'],
  SpanAttributes['gen_ai.prompt_json'],
  SpanAttributes['gen_ai.completion_json']
FROM otel_traces
WHERE ServiceName = 'ai-gateway'
  AND SpanId = '...'
LIMIT 1;
```

## Caveats

- **`gen_ai.usage.cost` is an estimate** from AI Gateway (token × price table),
  not the provider invoice.
- **Bodies are heavy** — don't `SELECT` prompt/completion JSON for large scans.
- **Metadata key cap** — CF limits how many `cf-aig-metadata` keys you can send.
- Filter failures out of cost rollups with `StatusCode != 'STATUS_CODE_ERROR'`.

## Reporting results

When the user asks "what did X cost," report:

1. The number with units (`$1,247.32`).
2. The time window.
3. The natural next breakdown (by model? by prompt version?).

Lead with the answer, then offer the breakdown.
