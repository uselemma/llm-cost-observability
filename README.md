# llm-cost-observability

LiteLLM proxy in front of Vercel AI Gateway and Fireworks AI, logging every request to a
ClickHouse table.

The point: every LLM call your services make gets a row in ClickHouse with
cost, tokens, latency, model, and per-request tags (feature, prompt version,
customer, A/B arm). You can answer "what did this feature cost last month?"
in SQL.

## Architecture

```
services ──▶ LiteLLM proxy ──▶ Vercel AI Gateway ──▶ provider
                         └──▶ Fireworks AI
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
| [proxy/config.yaml](proxy/config.yaml) | LiteLLM model list + auth wiring. Wildcard-routes Vercel AI Gateway models and Fireworks AI model IDs. |
| [proxy/auth.py](proxy/auth.py) | Static-keys auth hook. Parses `LITELLM_KEYS` env var. |
| [proxy/clickhouse_logger.py](proxy/clickhouse_logger.py) | `CustomLogger` callback that writes to ClickHouse. Async insert, swallows errors so a CH outage can't break LLM traffic. |
| [proxy/Dockerfile](proxy/Dockerfile) | Extends `litellm:main-stable`, adds `uv`-installed deps. |
| [docker-compose.yml](docker-compose.yml) | Runs the proxy locally. No DB sidecars — auth is env-var, ClickHouse is Cloud. |
| [sql/001_litellm_logs.sql](sql/001_litellm_logs.sql) | Table DDL. |
| [sql/queries.sql](sql/queries.sql) | Spend-by-model, cost-per-prompt, p95-by-feature, etc. |
| [.claude/skills/](.claude/skills/) | Agent skills for integrating services and querying the data. |

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
FIREWORKS_AI_API_KEY=...          # required for fireworks/* routes

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

Fireworks AI routes use the `fireworks/` prefix and map to Fireworks' hosted
`accounts/fireworks/models/<model-id>` names:

- `fireworks/kimi-k2p6`
- `fireworks/kimi-k2p5`
- `fireworks/<any-fireworks-model-id>`

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

### The contract

The proxy is OpenAI-compatible. Send standard chat-completion requests with
two additions:

- **Auth.** `Authorization: Bearer ${LITELLM_API_KEY}` — the key whose env
  half matches the service environment.
- **Tags.** Add `metadata.tags` to the request body — an array of `key:value`
  strings.

A minimal request:

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

Streaming (`"stream": true`) works identically; the logging callback fires
exactly once at stream end, so you get one ClickHouse row either way.

### Wrapping it

Don't sprinkle raw HTTP calls. Build a thin wrapper per service (or per
language) that:

1. Reads `LITELLM_BASE_URL` and `LITELLM_API_KEY` from env.
2. Takes a typed/validated `tags` argument with `feature` and `prompt`
   required.
3. Injects `metadata.tags` into the outgoing body.
4. Otherwise passes through to whatever HTTP client or SDK the service
   already uses (OpenAI SDK `extra_body`/`extraBody`, Vercel AI SDK with a
   custom `fetch`, raw `fetch`/`requests`).

The point is to make missing tags a compile-time or import-time error — a
call without `feature:` and `prompt:` lands in ClickHouse with no
attribution and becomes invisible in cost reports.

For agent-driven implementation guidance, see the
[llm-observability-integrate skill](.claude/skills/llm-observability-integrate/SKILL.md).

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
