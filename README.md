# llm-cost-observability

ClickHouse-backed cost dashboard for Cloudflare AI Gateway traffic.

LLM calls go through AI Gateway (`lemma-prod`). Gateway OTEL spans are ingested
into ClickHouse by the `aig-otel-collector` (ENG-401). This repo is **query + UI
only** — no LiteLLM proxy, no model routing, no write path.

```
services ──▶ Cloudflare AI Gateway (lemma-prod)
                    │ OTLP
                    ▼
             aig-otel-collector ──▶ ClickHouse aig.otel_traces
                                              ▲
engineer ──▶ Access SSO ──▶ aig-observability.uselemma.ai ──▶ FastAPI + SPA
```

## What's in here

| Path | Purpose |
|------|---------|
| [app/](app/) | FastAPI: `/api/*` over `aig.otel_traces` + static SPA |
| [dashboard/](dashboard/) | React UI (calls table, filters, CEL, detail drawer) |
| [sql/queries.sql](sql/queries.sql) | Example analytics SQL against OTEL spans |
| [sql/001_litellm_logs.sql](sql/001_litellm_logs.sql) | **Archived** — old LiteLLM table DDL (table dropped) |
| [.claude/skills/](.claude/skills/) | Agent skills: integrate via AI Gateway; query CH |

## Data source

Table: `aig.otel_traces`  
Filter: `ServiceName = 'ai-gateway'`

| API / CallRow field | Span source |
|---------------------|-------------|
| `request_id` | `SpanId` |
| `timestamp` | `Timestamp` |
| `model` / `provider` | `gen_ai.request.model` / `gen_ai.model.provider` |
| `spend_usd` | `gen_ai.usage.cost` |
| `prompt_tokens` / `completion_tokens` | `gen_ai.usage.input_tokens` / `output_tokens` |
| `latency_ms` | `Duration` (ns → ms) |
| `tags` | rebuilt from `feature`, `prompt`, `variant`, `project_id` attrs |
| `status` | `StatusCode` → `success` / `failure` |
| `input_messages` / `output_text` | `gen_ai.prompt_json` / `gen_ai.completion_json` |

Custom metadata from the `cf-aig-metadata` header lands as `SpanAttributes` keys
(see integrate skill).

## Local setup

### 1. Env

```bash
cp .env.example .env
```

```bash
CLICKHOUSE_HOST=<your-instance>.clickhouse.cloud
CLICKHOUSE_PORT=8443
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=...
CLICKHOUSE_DATABASE=aig
CLICKHOUSE_SECURE=true
```

Use the **LLM** ClickHouse credentials (`LLM_CLICKHOUSE_*` in AWS Secrets
Manager), not the product analytics cluster.

### 2. Run with Docker

```bash
docker compose up --build
```

Open http://localhost:8000 — no login; auth is Access in prod only.

### 3. Run without Docker

```bash
# API
python -m venv .venv && source .venv/bin/activate
pip install -r app/requirements.txt
export $(grep -v '^#' .env | xargs)
export PYTHONPATH=. DASHBOARD_DIST=dashboard/dist
uvicorn app.main:app --reload --port 8000

# Dashboard (separate terminal, optional for HMR)
cd dashboard && npm ci && npm run build
# or: npm run dev  (proxy /api to :8000 via vite.config)
```

## API

| Route | Notes |
|-------|-------|
| `GET /api/me` | Always `{ authenticated: true, env: null }` |
| `GET /api/calls` | Filters: `since`, `until`, `model`, `status`, `tag`, `q`, `cel`, `limit`, `offset` |
| `GET /api/calls/{span_id}` | Detail including message bodies |
| `GET /api/models` | Distinct models, last 7 days |
| `GET /api/tags` | Reconstructed `feature:` / `prompt:` / … tags, last 7 days |
| `GET /api/cel-fields` | Fields allowed in CEL filters |
| `GET /api/health` | Liveness |

There is no `/api/login` or `/api/logout`.

## Deploy / Zero Trust (infra follow-up)

Public hostname: **`aig-observability.uselemma.ai`**

In `uselemma/infra` (or Zero Trust dashboard), when hosting this container:

1. Deploy the image to the prod `lemma` namespace (port **8000**).
2. Cloudflare Tunnel public hostname `aig-observability.uselemma.ai` → service `:8000`.
3. Cloudflare Access application on that hostname — same IdP policy as
   `argocd` / `temporal`.
4. DNS CNAME → tunnel (proxied).

App env in the cluster: only
`CLICKHOUSE_HOST/PORT/USER/PASSWORD/DATABASE=aig` (+ `CLICKHOUSE_SECURE=true`).

In-app JWT validation of Access tokens is **out of scope** for v1 (same trust
model as other internal tunnel + Access tools).

## Related

- Ingest path: `infra/aig-otel-collector` (ENG-401)
- Gateway: Cloudflare AI Gateway `lemma-prod`
- Linear: [ENG-408](https://linear.app/uselemma/issue/ENG-408)
