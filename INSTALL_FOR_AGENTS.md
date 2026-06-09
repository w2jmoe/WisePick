# INSTALL_FOR_AGENTS — WisePick v0.2.4

> **Docs:** [Overview](./README.md) | [Integration & SDK](./README_API.md) | [Agent Protocol](./AGENTS.md) | [Verify](./VERIFY.md)

Agent Operator quick path to **Runtime-Aware Optimization** with persistent decision records, runtime feedback, and actual-tool observation.

---

## Quick Start (Hosted)

**Default endpoint:** `https://api.wishweaver.top`

Recommended for:

* Agent operators
* Runtime maintainers
* Early adopters

No infrastructure deployment required.

```bash
curl -s https://api.wishweaver.top/health
````

```python
from wisepick import WisePickClient
wp = WisePickClient(api_url="https://api.wishweaver.top")
```

Self-hosted deployment (your own ECS/Supabase, migration, and verification) is documented below.

---

## Self-hosted prerequisites

* Python 3.11+
* PostgreSQL / Supabase project with network access from the API host
* Tables `api_tool_specs`, `decisions`, and `feedback` must already exist in PostgreSQL/Supabase
* Existing deployments must run the migration scripts below before upgrading
* On first startup, `seed_tools()` populates missing rows in `api_tool_specs` only; it does not create database tables

---

## Migration order

If you are upgrading an existing database, apply the following scripts in order:

1. `scripts/migrate_v0_2_2.sql` — only if you still have the legacy pre-shared-feedback schema
2. `scripts/migrate_fallback_unknown.sql` — adds the persistent fallback decision anchor
3. `scripts/migrate_runtime_name.sql` — adds optional runtime attribution
4. `scripts/migrate_actual_tool_used.sql` — adds actual-tool attribution and the updated `tool_stats` view

If you already run the latest schema, re-running these scripts is safe.

---

## 1. Configure `DATABASE_URL`

Copy env template and set your Supabase connection string:

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Local / staging: Supabase project connection
DATABASE_URL=postgresql+psycopg2://postgres:YOUR_PASSWORD@YOUR_PROJECT_ID.supabase.co:5432/postgres

# Production: same variable, production Supabase credentials
```

SQLAlchemy accepts `postgresql+psycopg2://` or `postgresql://`.

---

## 2. Install and start

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Windows:

```bat
run.bat
```

Smoke check:

```bash
curl -s http://localhost:8000/health
```

Expected: `{"status":"ok",...}`

---

## 3. Runtime integration contract

A runtime should implement three integration points.

### 1) Decision

Before execution, call:

`POST /v1/decide`

Persist:

* `decision_id`
* `callable`
* `capability_id`

Treat `callable=false` as a valid response, not as a hard error.

When no capability matches, WisePick returns a persistent decision anchor using `fallback_unknown`. The runtime may execute its own fallback tool, but it should still keep the original `decision_id` for feedback.

### 2) Execution

If `callable=true`:

* optionally enforce `tool_choice`

If `callable=false`:

* runtime may use its own fallback strategy
* do not discard the decision
* do not re-decide unless the user intent changed

### 3) Feedback

After the first executed tool finishes, call:

`POST /v1/feedback`

Required:

* `decision_id`
* `success`
* `latency_ms`

Recommended:

* `runtime_name`
* `actual_tool_used`
* `token_cost`
* `result_quality`

Example:

```json
{
  "decision_id": "dec_xxx",
  "success": true,
  "latency_ms": 2400,
  "runtime_name": "hermes",
  "actual_tool_used": "browser_navigate"
}
```

If the runtime executed a different tool than WisePick recommended, keep `tool_key` aligned with the recommended decision for audit, and put the real execution path in `actual_tool_used`.

Do not send raw prompts, tool arguments, secrets, or customer data unless you intentionally need them for your own local observability. Minimal routing metadata is enough.

---

## 4. Why actual_tool_used matters

WisePick records:

* Recommended ECU
* Actual executed tool

This lets the Shared Feedback Pool learn:

* which ECU was recommended
* which tool was actually used
* execution success rate
* latency trends

Even when the runtime chooses its own internal tool, the actual runtime execution can still be attributed and measured.

---

## 5. 15-minute integration path

| Step | Action                                                 | Doc                                                                                          |
| ---- | ------------------------------------------------------ | -------------------------------------------------------------------------------------------- |
| 1    | `WisePickClient(api_url=...)`                          | [README_API.md § Step 1](./README_API.md#step-1--client-bootstrap)                           |
| 2    | Hard-route first completion via `inject_openai_choice` | [README_API.md § Step 2](./README_API.md#step-2--decide-before-the-first-completion)         |
| 3    | Align `function.name` ↔ `capability_id`                | [README_API.md § Step 3](./README_API.md#step-3--name-alignment-functionname--capability_id) |
| 4    | Release `tool_choice` after the first completion       | [README_API.md § Step 4](./README_API.md#step-4--release-after-the-first-completion)         |
| 5    | POST `/v1/feedback` after execution                    | [README_API.md § Step 5](./README_API.md#step-5--feedback-on-the-execution-hook)             |
| 6    | Load `wisepick.agent.v1` manifest                      | [AGENTS.md](./AGENTS.md)                                                                     |

---

## 6. Feedback loop verification (minimal)

Use the hosted endpoint (default):

```bash
# decide
curl -s -X POST https://api.wishweaver.top/v1/decide \
  -H "Content-Type: application/json" \
  -d '{"task":"Transcribe meeting audio"}'

# feedback (replace DECISION_ID from decide response)
curl -s -X POST https://api.wishweaver.top/v1/feedback \
  -H "Content-Type: application/json" \
  -d '{"decision_id":"DECISION_ID","success":true,"latency_ms":1200,"actual_tool_used":"browser_navigate","runtime_name":"hermes"}'

# duplicate feedback — must still return {"ok":true}, not 500
curl -s -X POST https://api.wishweaver.top/v1/feedback \
  -H "Content-Type: application/json" \
  -d '{"decision_id":"DECISION_ID","success":true,"latency_ms":1200}'
```

Self-hosted smoke (replace host if not local):

```bash
curl -s http://localhost:8000/health
```

Full checklist: [VERIFY.md](./VERIFY.md)

SQL check (Supabase):

```sql
SELECT tool_key, feedback_count, success_rate
FROM tool_stats
WHERE feedback_count > 0;
```

Optional attribution checks:

```sql
SELECT tool_key, observation_count, success_count, failure_count, last_runtime_name
FROM observed_tools
ORDER BY last_seen_at DESC;

SELECT tool_key, actual_tool_used, runtime_name, success, latency_ms
FROM feedback
ORDER BY created_at DESC
LIMIT 20;
```

---

## 7. Operator checklist

**Hosted (default):**

* [ ] Runtime uses `https://api.wishweaver.top` as `api_url` / `WISEPICK_API_URL`
* [ ] `/health` returns 200
* [ ] decide → feedback → duplicate feedback smoke passes
* [ ] `actual_tool_used` appears in feedback for real runtime executions

**Self-hosted (advanced):**

* [ ] `DATABASE_URL` set in `.env`
* [ ] migration scripts applied
* [ ] `/health` returns 200
* [ ] decide → feedback → duplicate feedback smoke passes
* [ ] `tool_stats.feedback_count` increments after feedback
* [ ] `observed_tools` grows for real runtime tool usage
* [ ] Runtime sends feedback with persisted `decision_id` only

```
