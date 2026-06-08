# INSTALL_FOR_AGENTS — WisePick v0.2.2

> **Docs:** [Overview](./README.md) | [Integration & SDK](./README_API.md) | [Agent Protocol](./AGENTS.md) | [Verify](./VERIFY.md) | [Migration v0.2.2](./docs/MIGRATION_v0_2_2.md)

Agent Operator quick path to **Hosted Shared Feedback Pool MVP** (v0.2.2).

---

## Quick Start (Hosted)

**Default endpoint:** `https://api.wishweaver.top`

Recommended for:

* Agent operators
* Runtime maintainers
* Early adopters

No infrastructure deployment required. Status: early operator validation.

```bash
curl -s https://api.wishweaver.top/health
```

```python
from wisepick import WisePickClient
wp = WisePickClient(api_url="https://api.wishweaver.top")
```

Self-hosted deployment (your own ECS/Supabase, migration, and verification) is documented in the sections below.

---

## Self-hosted prerequisites

- Python 3.11+
- PostgreSQL / Supabase project with network access from the API host
- Tables `api_tool_specs`, `decisions`, and `feedback` must already exist in PostgreSQL/Supabase
- Existing deployments must run `scripts/migrate_v0_2_2.sql` before upgrading to v0.2.2
- On first startup, `seed_tools()` populates missing rows in `api_tool_specs` only; it does not create database tables

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

## 2. Migration order (v0.2.2 — required before Hosted Feedback Pool)

Execute **before** or during a maintenance window, **before** relying on shared feedback learning:

1. Backup tables (see [docs/MIGRATION_v0_2_2.md](./docs/MIGRATION_v0_2_2.md))
2. Run `scripts/migrate_v0_2_2.sql` in Supabase SQL Editor (full script, one session)
3. Confirm Section 5 verification queries return `PASS`
4. Deploy application **v0.2.2+**

Do **not** skip migration on existing databases that still use legacy `tools`-driven `tool_stats`.

### 2b. Migration — `actual_tool_used` (recommended for accurate ROI)

After v0.2.2, run `scripts/migrate_actual_tool_used.sql` in Supabase SQL Editor when runtimes may execute a different tool than WisePick recommended. Rebuilds `tool_stats` to attribute feedback ROI to `COALESCE(actual_tool_used, tool_key)`.

---

## 3. Install and start

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

On first startup, `seed_tools()` populates `api_tool_specs` when rows are missing.

---

## 4. Feedback loop verification (minimal)

Use the hosted endpoint (default):

```bash
# decide
curl -s -X POST https://api.wishweaver.top/v1/decide \
  -H "Content-Type: application/json" \
  -d '{"task":"Transcribe meeting audio"}'

# feedback (replace DECISION_ID from decide response)
curl -s -X POST https://api.wishweaver.top/v1/feedback \
  -H "Content-Type: application/json" \
  -d '{"decision_id":"DECISION_ID","success":true,"latency_ms":1200}'

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

---

## Runtime Integration Contract

A Runtime should implement three integration points:

### 1. Decision

Before execution:

POST /v1/decide

Store:

- decision_id
- callable
- capability_id

### 2. Execution

If callable=true:

- optionally enforce tool_choice

If callable=false:

- runtime may use its own fallback strategy

### 3. Feedback

After the first executed tool:

POST /v1/feedback

Required:

- decision_id
- success
- latency_ms

Recommended:

- runtime_name
- actual_tool_used

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

---

## Why actual_tool_used matters

WisePick records:

- Recommended ECU
- Actual executed tool

This allows the Shared Feedback Pool to learn:

- which ECU was recommended
- which tool was actually used
- execution success rate
- latency trends

Even when the runtime chooses its own internal tool.

---

## 5. 15-minute integration path

| Step | Action | Doc |
| --- | --- | --- |
| 1 | `WisePickClient(api_url=...)` | [README_API.md § Step 1](./README_API.md#step-1--client-bootstrap) |
| 2 | Hard-route first completion via `inject_openai_choice` | [README_API.md § Step 2](./README_API.md#step-2--hard-route-the-first-llm-completion) |
| 3 | Align `function.name` ↔ `capability_id` | [README_API.md § Step 3](./README_API.md#step-3--name-alignment-functionname--capability_id) |
| 4 | Release `tool_choice` after first completion | [README_API.md § Step 4](./README_API.md#step-4--multi-turn-release-after-the-first-completion) |
| 5 | POST `/v1/feedback` after every execution | [README_API.md § Step 5](./README_API.md#step-5--feedback-on-the-execution-hook) |
| 6 | Load `wisepick.agent.v1` manifest | [AGENTS.md](./AGENTS.md) |

Runtime adapters (optional): SafeAgent / ChainWeaver — see [README_API.md § Runtime adapters](./README_API.md#runtime-adapters).

---

## Operator checklist

**Hosted (default):**

- [ ] Runtime uses `https://api.wishweaver.top` as `api_url` / `WISEPICK_API_URL`
- [ ] `/health` returns 200
- [ ] decide → feedback → duplicate feedback smoke passes

**Self-hosted (advanced):**

- [ ] `DATABASE_URL` set in `.env`
- [ ] `scripts/migrate_v0_2_2.sql` executed (existing DB)
- [ ] `/health` returns 200
- [ ] decide → feedback → duplicate feedback smoke passes
- [ ] `tool_stats.feedback_count` increments after feedback
- [ ] Runtime sends feedback with persisted `decision_id` only (no ghost IDs after v0.2.2)
