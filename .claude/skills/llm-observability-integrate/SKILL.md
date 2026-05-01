---
name: llm-observability-integrate
description: Use when adding a new LLM call to a service, or wiring an existing service to the company LiteLLM proxy so its calls get logged to ClickHouse. Triggers when the user mentions calling Claude/GPT/an LLM, "instrument" or "add observability" to LLM calls, switching from a direct provider SDK to the proxy, or asks how to send tags. Don't use this for general LLM-coding questions unrelated to our proxy.
---

# Integrating a service with the LLM cost observability proxy

All LLM traffic at this company goes through a self-hosted LiteLLM proxy that
sits in front of Vercel AI Gateway. The proxy logs every request to ClickHouse
with cost, tokens, latency, bodies, and per-request tags. Direct calls to
provider SDKs (`openai`, `anthropic`) or to Vercel AI Gateway bypass that
logging and **must not** be added to new code.

The full project lives at https://github.com/uselemma/llm-cost-observability.

This skill describes the integration **contract** — what the proxy expects
on the wire — not a specific client library. Implement it in whatever
language and HTTP/SDK style fits the service you're working in.

## The contract

1. **Endpoint.** The proxy is OpenAI-compatible at
   `${LITELLM_BASE_URL}/v1/chat/completions` (and `/v1/completions`,
   `/v1/embeddings`, etc.). Any OpenAI-format request body works.
2. **Auth.** `Authorization: Bearer ${LITELLM_API_KEY}`. Each environment has
   its own key — dev services hold the dev key, prod services hold the prod
   key. The proxy stamps the matching `env:dev` or `env:prod` tag onto every
   row from that key, so a service physically can't lie about its env.
3. **Model name.** Pass either the short form `<provider>/<model>` (e.g.
   `anthropic/claude-opus-4.6`, `openai/gpt-4.1`) or the full slug
   `vercel_ai_gateway/<provider>/<model>`. A bare model name without a
   provider prefix won't route.
4. **Tags.** Add `metadata.tags` to the request body — an array of
   `key:value` strings. `feature` and `prompt` are required; `customer` and
   `experiment` are optional; `env` is **server-stamped, do not set**.
   Unknown keys are reserved.
5. **Streaming.** `stream: true` works. The proxy fires its logging callback
   exactly once at stream end, so streaming and non-streaming each produce
   one ClickHouse row.

A complete, minimal request:

```json
POST /v1/chat/completions
Authorization: Bearer sk-...

{
  "model": "anthropic/claude-opus-4.6",
  "messages": [{"role": "user", "content": "..."}],
  "metadata": {
    "tags": [
      "feature:summarization",
      "prompt:summarize-v3",
      "customer:acme"
    ]
  }
}
```

That's the entire contract. Everything below is guidance on how to apply it
correctly.

## Implementation guidance

### Pick a tag-aware wrapper, don't sprinkle raw HTTP calls

Whatever language you're in, build (or reuse) a thin layer that:

1. Holds the base URL and API key from env vars (`LITELLM_BASE_URL`,
   `LITELLM_API_KEY`).
2. Takes a typed/validated `tags` argument with `feature` and `prompt`
   required.
3. Injects `metadata.tags` into the outgoing request body.
4. Otherwise passes through to whatever HTTP client or SDK the service
   already uses (OpenAI SDK, Vercel AI SDK, `requests`, `fetch`, etc.).

The point is to make missing-tag a compile-time or import-time error, not a
silent runtime hole. A call without `feature:` and `prompt:` will land in
ClickHouse with no attribution and become invisible in cost reports.

### Vercel AI SDK (TypeScript) — fetch wrapper pattern

The OpenAI-compatible provider doesn't expose a clean per-call "extra body"
hook in every version. Inject tags via a custom `fetch`:

```ts
import { createOpenAICompatible } from '@ai-sdk/openai-compatible';

function fetchWithTags(tags: Record<string, string>): typeof fetch {
  const arr = Object.entries(tags).map(([k, v]) => `${k}:${v}`);
  return async (input, init) => {
    const body = init?.body ? JSON.parse(init.body as string) : {};
    body.metadata = {
      ...(body.metadata ?? {}),
      tags: [...(body.metadata?.tags ?? []), ...arr],
    };
    return fetch(input, { ...init, body: JSON.stringify(body) });
  };
}

const provider = createOpenAICompatible({
  name: 'litellm',
  baseURL: process.env.LITELLM_BASE_URL!,
  apiKey: process.env.LITELLM_API_KEY!,
  fetch: fetchWithTags({ feature: 'summarization', prompt: 'summarize-v3' }),
});
```

### OpenAI SDK (any language) — `extra_body` / `extraBody`

Most OpenAI SDK builds support an `extra_body` (Python) or `extraBody`
(JS/TS) parameter that gets merged into the request body verbatim. Pass
`{"metadata": {"tags": [...]}}` there.

### Raw HTTP

Just put `metadata.tags` in the JSON body. It really is that simple.

## Tag conventions

| Key | Required | Example | Notes |
|-----|----------|---------|-------|
| `feature` | yes | `feature:summarization` | The product feature making the call. Pick a stable name; don't use IDs. |
| `prompt` | yes | `prompt:summarize-v3` | Specific prompt template + version. Bump the version when the prompt body changes. |
| `customer` | when applicable | `customer:acme` | Tenant ID for multi-tenant cost attribution. |
| `experiment` | when applicable | `experiment:concise-arm-b` | A/B arm. |
| `env` | **don't set** | `env:prod` | Server-stamped from the API key. |

Keep tag values low-cardinality. **Never** put request IDs, user emails, or
free-form text into tags — they explode ClickHouse cardinality and degrade
queries. The `metadata` JSON column is the escape hatch for high-cardinality
fields you want to keep around for ad-hoc queries.

## Model naming

The proxy wildcard-routes any Vercel AI Gateway model. Two equivalent forms:

- `anthropic/claude-opus-4.6` ← short, recommended
- `vercel_ai_gateway/anthropic/claude-opus-4.6` ← full slug

Same patterns for `openai/`, `xai/`, `google/`. See [proxy/config.yaml](../../proxy/config.yaml).

Cost is computed automatically for any model in [LiteLLM's pricing map](https://github.com/BerriAI/litellm/blob/main/litellm/model_prices_and_context_window_backup.json).
For models too new to be in the map, `spend_usd` will be 0 — flag that to the
user; they need to add `input_cost_per_token` / `output_cost_per_token`
overrides to the model's `litellm_params` in [proxy/config.yaml](../../proxy/config.yaml).

## Common mistakes to avoid

- **Bypassing the proxy** by importing `openai`/`@ai-sdk/openai` directly
  with a provider key. New code should not do this.
- **Setting `env:` client-side.** It's server-stamped from the API key.
- **Forgetting the version on `prompt:`.** A prompt's identity is its
  template + version. Without the version, you can't compare v2 vs v3 cost.
- **Putting customer email or user ID into a tag.** Use `customer:<tenant_id>`
  with a stable, low-cardinality identifier.
- **Skipping the wrapper** and calling the proxy with raw `fetch`/`requests`.
  That works, but you lose tag validation and will eventually ship a call
  with no `feature:` tag, which is invisible in cost reports.

## Verifying it worked

After your first call, query the table to confirm:

```sql
SELECT timestamp, model, team, spend_usd, total_tokens, tags
FROM litellm_logs
WHERE timestamp >= now() - INTERVAL 5 MINUTE
ORDER BY timestamp DESC LIMIT 5;
```

You should see your call with `team='dev'` (or `prod`), non-zero
`spend_usd`, and `tags` containing `env:dev`, your `feature:`, and your
`prompt:`. If `tags` only has `env:`, the request body wasn't carrying
`metadata.tags` — check the wrapper.
