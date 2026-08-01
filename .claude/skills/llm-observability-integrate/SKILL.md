---
name: llm-observability-integrate
description: Use when adding a new LLM call to a service, or wiring a service to Cloudflare AI Gateway so calls appear in aig.otel_traces / the cost dashboard. Triggers when the user mentions calling Claude/GPT/an LLM, "instrument" or "add observability" to LLM calls, cf-aig-metadata, AI Gateway, or asks how to send feature/prompt tags. Don't use for general LLM-coding questions unrelated to our gateway.
---

# Integrating a service with Cloudflare AI Gateway (cost observability)

All LLM traffic goes through **Cloudflare AI Gateway** (`lemma-prod`). The
gateway exports GenAI OTEL spans to ClickHouse (`aig.otel_traces`) via the
`aig-otel-collector` (ENG-401). The cost dashboard in
https://github.com/uselemma/llm-cost-observability reads that table.

There is **no LiteLLM proxy**. Do not point new code at a LiteLLM base URL or
write to `litellm_logs`.

In Lemma services, prefer the shared helper in `shared/common/ts/ai/tracing.ts`
(or the equivalent Python helper) — it already sets gateway URL, auth, and
`cf-aig-metadata`.

## The contract

1. **Endpoint.** OpenAI-compatible (or provider-native) URL through AI Gateway,
   e.g. `https://gateway.ai.cloudflare.com/v1/{account_id}/{gateway_id}/compat/...`
   or the provider path (`/anthropic/...`, `/openai/...`).
2. **Auth.** Gateway token (`CF_AIG_TOKEN` / account secrets) — not a LiteLLM key.
3. **Metadata (tags).** Send a JSON object on the `cf-aig-metadata` header.
   Keys become `SpanAttributes` in ClickHouse. Required for attribution:
   `feature` and `prompt`. Optional: `variant`, `project_id`, and other
   low-cardinality keys (CF caps the number of metadata keys per request).
4. **Trace linking (optional).** `cf-aig-otel-trace-id` /
   `cf-aig-otel-parent-span-id` nest the gateway span under your app trace.

Minimal example:

```bash
curl "https://gateway.ai.cloudflare.com/v1/${CF_ACCOUNT_ID}/${CF_AIG_GATEWAY_ID}/compat/chat/completions" \
  -H "Authorization: Bearer ${CF_AIG_TOKEN}" \
  -H "Content-Type: application/json" \
  -H 'cf-aig-metadata: {"feature":"summarization","prompt":"summarize-v3","variant":"default"}' \
  -d '{"model":"anthropic/claude-sonnet-4-5","messages":[{"role":"user","content":"..."}]}'
```

## Tag / metadata conventions

| Key | Required | Example | Notes |
|-----|----------|---------|-------|
| `feature` | yes | `signal-pipeline` | Product feature. Stable name, not an ID. |
| `prompt` | yes | `summarize-v3` | Prompt template + version. |
| `variant` | when applicable | `structured` | A/B or prompt arm. |
| `project_id` | when applicable | uuid | Tenant / project attribution. |

Keep values **low-cardinality**. Never put request IDs, emails, or free-form
text in metadata — they explode cardinality.

The dashboard rebuilds tags as `feature:…`, `prompt:…`, `variant:…`,
`project_id:…` for filters.

## TypeScript — use the shared tracer

```ts
// Prefer shared/common/ts/ai/tracing.ts (or your service's wrap of it).
// It sets cf-aig-metadata from { feature, prompt, variant, project_id, ... }.
```

If you must call the gateway directly, attach:

```ts
headers: {
  'cf-aig-metadata': JSON.stringify({
    feature: 'summarization',
    prompt: 'summarize-v3',
  }),
}
```

## Verifying it worked

After a call, in ClickHouse (database `aig`):

```sql
SELECT
  Timestamp,
  SpanAttributes['gen_ai.request.model'] AS model,
  SpanAttributes['feature'] AS feature,
  SpanAttributes['prompt'] AS prompt,
  toFloat64OrZero(SpanAttributes['gen_ai.usage.cost']) AS spend_usd
FROM otel_traces
WHERE ServiceName = 'ai-gateway'
  AND Timestamp >= now() - INTERVAL 5 MINUTE
ORDER BY Timestamp DESC
LIMIT 5;
```

You should see your `feature` / `prompt` and a non-null model. Cost may be `0`
if the provider did not return token usage.

Also check the UI at https://aig-observability.uselemma.ai (Cloudflare Access).
