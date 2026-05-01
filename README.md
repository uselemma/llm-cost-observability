# llm-cost-observability

LiteLLM proxy in front of Vercel AI Gateway, logging every request to a
ClickHouse table.

The point: every LLM call your services make gets a row in ClickHouse with
cost, tokens, latency, model, and per-request tags (feature, prompt version,
customer, A/B arm). You can answer "what did this feature cost last month?"
in SQL.

## Architecture

```
services ──▶ LiteLLM proxy ──▶ Vercel AI Gateway ──▶ provider
              │
              └── async insert ──▶ ClickHouse Cloud
```

- **LiteLLM proxy** ([proxy/](proxy/)) — OpenAI-compatible endpoint. Auth via
  static env-var keys (no Postgres). Every successful or failed call fires a
  custom callback that writes one row to ClickHouse.
- **ClickHouse** — analytics warehouse. Schema in [sql/001_litellm_logs.sql](sql/001_litellm_logs.sql).
  Bodies (input messages, output text, reasoning) are stored alongside metrics
  with ZSTD compression and a 180-day TTL.
- **Client wrappers** ([client/](client/) for Python, snippet below for TS) —
  point at the proxy, enforce a tagging contract.

## What's in here

| Path | Purpose |
|------|---------|
| [proxy/config.yaml](proxy/config.yaml) | LiteLLM model list + auth wiring. Wildcard-routes any Vercel AI Gateway model. |
| [proxy/auth.py](proxy/auth.py) | Static-keys auth hook. Parses `LITELLM_KEYS` env var. |
| [proxy/clickhouse_logger.py](proxy/clickhouse_logger.py) | `CustomLogger` callback that writes to ClickHouse. Async insert, swallows errors so a CH outage can't break LLM traffic. |
| [proxy/Dockerfile](proxy/Dockerfile) | Extends `litellm:main-stable`, adds `uv`-installed deps. |
| [docker-compose.yml](docker-compose.yml) | Runs the proxy locally. No DB sidecars — auth is env-var, ClickHouse is Cloud. |
| [sql/001_litellm_logs.sql](sql/001_litellm_logs.sql) | Table DDL. |
| [sql/queries.sql](sql/queries.sql) | Spend-by-model, cost-per-prompt, p95-by-feature, etc. |
| [client/llm_client/client.py](client/llm_client/client.py) | Python wrapper enforcing the tag schema. |
| [scripts/smoke_test.py](scripts/smoke_test.py) | End-to-end check: send a chat call, verify a row lands in CH. |

## Setup (local dev and prod use the same path)

ClickHouse Cloud is the only persistent dependency, and dev + prod both point
at it (separate services or databases).

### 1. Configure environment

```bash
cp .env.example .env
```

Fill in:

```bash
# Two keys, one per env. Generate fresh:
#   echo "sk-$(openssl rand -hex 24):dev,sk-$(openssl rand -hex 24):prod"
LITELLM_KEYS="sk-...:dev,sk-...:prod"

VERCEL_AI_GATEWAY_API_KEY=...

CLICKHOUSE_HOST=<your-instance>.clickhouse.cloud
CLICKHOUSE_PORT=8443                # HTTPS port for clickhouse-connect
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=...
CLICKHOUSE_DATABASE=default
CLICKHOUSE_SECURE=true
```

> The Cloud DSN you'll see in the UI uses port `9440` (native protocol). The
> proxy uses HTTP(S), so use `8443` here. Same host, same creds.

### 2. Apply the schema

In the ClickHouse Cloud SQL console, paste the contents of
[sql/001_litellm_logs.sql](sql/001_litellm_logs.sql) and run.

### 3. Start the proxy

```bash
docker compose up --build
```

Watch for `Uvicorn running on http://0.0.0.0:4000`.

### 4. Smoke test

Send a chat completion. Use the `dev` half of `LITELLM_KEYS`:

```bash
curl http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-...DEV..." \
  -H "Content-Type: application/json" \
  -d '{
    "model": "anthropic/claude-opus-4.6",
    "messages": [{"role": "user", "content": "hello in 5 words"}],
    "metadata": {"tags": ["feature:smoke", "prompt:smoke-v1"]}
  }'
```

Streaming:

```bash
curl -N http://localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer sk-...DEV..." \
  -H "Content-Type: application/json" \
  -d '{
    "model": "anthropic/claude-opus-4.6",
    "stream": true,
    "messages": [{"role": "user", "content": "count to 5"}],
    "metadata": {"tags": ["feature:smoke", "prompt:smoke-stream-v1"]}
  }'
```

Verify the row landed:

```sql
SELECT timestamp, model, team, spend_usd, total_tokens, tags
FROM litellm_logs
ORDER BY timestamp DESC LIMIT 5;
```

You should see `team='dev'` and `tags` containing `env:dev`,
`feature:smoke`, `prompt:smoke-v1`.

## Deploying to prod

The proxy is stateless; deploy as you would any container.

1. Run two replicas behind a load balancer for redundancy (PRD §6 risk row 1).
2. Set the same env vars; in prod, the `LITELLM_KEYS` `prod` half is the only
   one services use. Rotate by updating the env var and redeploying.
3. Apply [sql/001_litellm_logs.sql](sql/001_litellm_logs.sql) against your
   prod ClickHouse Cloud service.
4. Lock down: only the proxy should hold the `VERCEL_AI_GATEWAY_API_KEY`. Use
   network policy to block direct Vercel calls from app services (PRD Phase 3).

## Integration

### Models

The proxy wildcard-forwards anything under `vercel_ai_gateway/`. Clients can
use either form:

- `anthropic/claude-opus-4.6` ← short form (recommended)
- `vercel_ai_gateway/anthropic/claude-opus-4.6` ← full slug

Same patterns for `openai/`, `xai/`, `google/`. See [proxy/config.yaml](proxy/config.yaml).

Cost is computed automatically for any model in
[LiteLLM's pricing map](https://github.com/BerriAI/litellm/blob/main/litellm/model_prices_and_context_window_backup.json).
For bleeding-edge models that aren't in the map yet (`spend_usd=0`), add an
explicit `litellm_params.input_cost_per_token` / `output_cost_per_token`
override for that model in the config.

### Tag contract

| Key | Required | Example |
|-----|----------|---------|
| `feature` | yes | `feature:summarization` |
| `prompt` | yes | `prompt:summarize-v3` |
| `customer` | when applicable | `customer:acme` |
| `experiment` | when applicable | `experiment:concise-arm-b` |
| `env` | **server-stamped** | `env:prod` (do not set client-side) |

`env` is derived from the API key by the proxy's auth hook. Clients shouldn't
include it — services in dev physically can't lie about being prod.

### Python services

```bash
pip install ./client    # or publish from `client/` to your internal index
```

```python
import os
from llm_client import LLMClient

os.environ["LITELLM_BASE_URL"] = "http://litellm-proxy.internal:4000"
os.environ["LITELLM_API_KEY"] = "sk-...PROD..."

llm = LLMClient()

resp = llm.chat(
    model="anthropic/claude-opus-4.6",
    messages=[{"role": "user", "content": "..."}],
    tags=["feature:summarization", "prompt:summarize-v3", "customer:acme"],
)
```

The wrapper raises `TagValidationError` if `feature` or `prompt` are missing,
or if any unknown tag key is passed.

### TypeScript services (Vercel AI SDK)

```ts
// lib/llm.ts
import { createOpenAICompatible } from '@ai-sdk/openai-compatible';
import type { LanguageModel } from 'ai';

type Tags = {
  feature: string;
  prompt: string;
  customer?: string;
  experiment?: string;
};

function tagsToArray(t: Tags): string[] {
  return Object.entries(t)
    .filter(([, v]) => v != null && v !== '')
    .map(([k, v]) => `${k}:${v}`);
}

function fetchWithTags(tags: Tags): typeof fetch {
  const arr = tagsToArray(tags);
  return async (input, init) => {
    const body = init?.body ? JSON.parse(init.body as string) : {};
    body.metadata = {
      ...(body.metadata ?? {}),
      tags: [...(body.metadata?.tags ?? []), ...arr],
    };
    return fetch(input, { ...init, body: JSON.stringify(body) });
  };
}

export function llm(modelId: string, tags: Tags): LanguageModel {
  const provider = createOpenAICompatible({
    name: 'litellm',
    baseURL: process.env.LITELLM_BASE_URL!,
    apiKey: process.env.LITELLM_API_KEY!,
    fetch: fetchWithTags(tags),
  });
  return provider(modelId);
}
```

Usage:

```ts
import { generateText, streamText } from 'ai';
import { llm } from '@/lib/llm';

const { text } = await generateText({
  model: llm('anthropic/claude-opus-4.6', {
    feature: 'summarization',
    prompt: 'summarize-v3',
    customer: 'acme',
  }),
  messages: [{ role: 'user', content: '...' }],
});
```

## Operations

### Common queries

See [sql/queries.sql](sql/queries.sql) for the canonical set:
- spend by model, current month
- cost per prompt template, last 7 days
- p95 latency by feature, last 24h
- spend by customer
- daily spend trend

### Troubleshooting

**`spend_usd=0`** — model isn't in LiteLLM's pricing map. Either pin to a
priced model or add `input_cost_per_token` / `output_cost_per_token` to the
model's `litellm_params`.

**`401 invalid api key`** — bearer token doesn't match any entry in
`LITELLM_KEYS`. Check the env var on the running container.

**Row not landing in ClickHouse** — the callback swallows errors by design
(LLM traffic must not break on a CH outage). Find the traceback in proxy
logs:

```bash
docker compose logs litellm | grep clickhouse_logger
```

**Tags missing from row** — the auth hook injects `env:` server-side; client
tags come from `metadata.tags` in the request body. Both should appear,
deduped, in the `tags` array column. If only `env:` shows up, the client
isn't sending `metadata.tags` — verify the request body.

### Cost reconciliation

LiteLLM's pricing is list price (or whatever you set in the config); your
Vercel invoice is the ground truth. Reconcile monthly:

```sql
SELECT toStartOfMonth(timestamp) AS month, sum(spend_usd) AS our_estimate
FROM litellm_logs WHERE status = 'success'
GROUP BY month ORDER BY month DESC;
```

Compare against the Vercel invoice. Persistent delta = a known offset to
document; sudden delta = something changed (new model, missing pricing entry).

## Out of scope

Per PRD §2, this project is observability-only. **Not** in here:
- Hard budget enforcement (would need LiteLLM Enterprise tier).
- A UI / debug browser. Engineers query ClickHouse directly via Grafana,
  Metabase, or the Cloud SQL console.
- Replacing Vercel AI Gateway. Vercel remains the provider boundary.
