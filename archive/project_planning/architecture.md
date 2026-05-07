# WisePick API v0 Architecture

## 1. Design Goal

WisePick API v0 is not an agent platform.
It is a minimal decision infrastructure for one transparent loop:

1. `POST /v1/decide`
2. return `tool_key + reason + confidence`
3. receive `feedback`
4. update database-visible tool success metrics

The goal of v0 is:

- open source friendly
- easy to audit
- easy to self-host
- easy to deploy on Vercel
- explicit about what WisePick does and does not do

## 2. What WisePick Core Owns

WisePick core is responsible for only these concerns:

- store a registry of tools in Postgres
- accept a task and select one `tool_key`
- produce a transparent explanation and trace payload
- record the final decision
- accept outcome feedback for that decision
- derive per-tool success metrics from feedback

In v0, WisePick core does not execute the tool. It decides.

## 3. What External Agent Developers Own

The following belong to the caller, not WisePick core:

- tool authentication and API keys for third-party tools
- actual tool execution
- retries, fallbacks, and orchestration graphs
- prompt engineering
- memory, long-term planning, agent state
- ranking marketplaces, governance systems, social graphs
- non-transparent ML scoring pipelines

WisePick returns a recommended tool and a trace.
The caller decides whether and how to execute it.

## 4. Product Scope

### Core API

- `POST /v1/decide`
- `POST /v1/feedback`

### Non-core but acceptable infra endpoints

- `GET /`
- `GET /healthz`

Everything else should be removed from the v0 surface area or marked internal.

## 5. Minimal Request Flow

### Decide flow

1. client sends task and optional constraints
2. service loads enabled tools from Postgres
3. service applies transparent bootstrap rules
4. service calculates a simple deterministic score
5. service writes one row to `decisions`
6. service returns `decision_id`, `tool_key`, `reason`, `confidence`, `trace`

### Feedback flow

1. client sends `decision_id` and outcome
2. service verifies the decision exists
3. service writes one row to `feedback`
4. `tool_stats` view reflects the latest success metrics

This keeps the loop auditable:
decision first, outcome second, aggregate last.

## 6. Minimal Directory Structure

The current repo already has a usable FastAPI layout.
Do not create a new platform. Refactor the existing layout down to this:

```text
app/
  main.py
  core/
    config.py
    database.py
  models/
    tool.py
    decision.py
    feedback.py
  routers/
    decide.py
    feedback.py
  schemas/
    decide.py
    feedback.py
  services/
    decision_engine.py
    feedback_service.py
    bootstrap_rules.py
README.md
architecture.md
db_schema.sql
implementation_plan.md
```

Notes:

- keep the existing `app/` project instead of creating a new monorepo
- rename old demo-oriented models gradually, not all at once
- remove agent-ready wrappers that are not required for the v0 contract

## 7. Runtime Shape

### Application layer

- FastAPI
- SQLAlchemy
- Supabase Postgres

### Deploy target

- preferred target: Vercel
- keep the server minimal enough that it can also run with `uvicorn` locally

### Vercel shape

Two minimal options are acceptable:

1. keep `app/main.py` as the ASGI app and expose it through a tiny Vercel adapter
2. if needed, add a very small `api/index.py` that imports `app.main:app`

No extra service mesh, queue, worker, or scheduler is required for v0.

## 8. Data Model

### `tools`

Purpose:

- canonical registry of selectable tools
- audit which tools were available at decision time

Required fields:

- `id`
- `tool_key`
- `name`
- `description`
- `capabilities` as `jsonb`
- `enabled`
- `metadata`
- `bootstrap_weight`
- `created_at`
- `updated_at`

### `decisions`

Purpose:

- immutable record of each decision returned by the API

Required fields:

- `id`
- `decision_id`
- `task`
- `context`
- `constraints`
- `selected_tool_key`
- `reason`
- `confidence`
- `score_breakdown`
- `explain`
- `trace`
- `bootstrap_version`
- `created_at`

### `feedback`

Purpose:

- immutable outcome records tied to one decision

Required fields:

- `id`
- `decision_id`
- `tool_key`
- `outcome`
- `success`
- `latency_ms`
