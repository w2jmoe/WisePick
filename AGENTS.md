# AGENTS.md — WisePick Decision API (Machine Reader)

> [!TIP]
> **Machine-Optimized Spec:** This document is structured for Coding Agents (Cursor, Cline, Devin, etc.).
> 
> **Human developers:** refer to [README_API.md](./README_API.md) for deployment and environment setup.

**Audience:** AI Agent Runtime / Coding Agents only (Cursor, Cline, Claude Code, OpenHands, Devin, etc.).

**Prerequisite:** Index [README_API.md](./README_API.md) first. Complete deployment, environment, and configuration there. This file does **not** duplicate install or ops steps.

**Scope:** Agent runtime semantics + decision workflow only.

---

## What WisePick Is

- **Decision layer:** Maps a natural-language **task** → one **Executable Capability Unit (ECU)**.
- **Routing + learning:** Uses capability match, execution success stats, and bootstrap weights (see `README_API.md` scoring).
- **Outputs:** `decision_id`, `capability_id`, `provider`, `execution_type`, `callable`, `confidence`, plus `reason`, `explain`, `trace`.

---

## What WisePick Is Not

- **Not** an MCP server/runtime.
- **Not** a tool executor (does not call external APIs, MCP tools, or local functions).
- **Not** a workflow engine or orchestrator.
- **Not** responsible for credential management, retries, or side-effect handling at execution time.

Your runtime executes; WisePick **routes and records feedback**.

---

## Architecture

- **Observability:** Background-thread telemetry using Langfuse (`mcp.route_decision.v1` protocol).

---

## Runtime Adapter Pattern

- **Runtime** keeps execution ownership, credential ownership, and memory ownership.
- **WisePick** returns a single routing decision per `POST /v1/decide`; it does not execute tools or retain session state.

Minimal router mapping (Hermes-compatible tool name extraction): [`examples/wisepick_router.py`](./examples/wisepick_router.py).

---

## HTTP Surface (v0)

| Method | Path | Role |
|--------|------|------|
| GET | `/health` | Liveness |
| POST | `/v1/decide` | Task → ECU |
| POST | `/v1/feedback` | Outcome → updates routing stats |

Base URL example: `http://localhost:8000` (replace with deployed host).

---

## Calling `/v1/decide`

**Request (minimal):**

```json
{
  "task": "Transcribe today's meeting audio"
}
```

**Request (with optional fields):**

```json
{
  "task": "Summarize this technical document",
  "context": {
    "language": "Chinese",
    "domain": "engineering"
  },
  "constraints": {
    "max_cost": 10.0,
    "timeout_seconds": 300
  }
}
```

**Response (ECU-shaped excerpt):**

```json
{
  "decision_id": "dec_abc123def4567890",
  "capability_id": "audio_transcription",
  "execution_type": "api",
  "provider": "feishu_minutes",
  "callable": true,
  "confidence": 0.75,
  "reason": "...",
  "explain": {},
  "trace": {}
}
```

**Legacy:** `tool_key` may appear and mirrors `provider` for backward compatibility; prefer `provider` + `capability_id` for new integrations.

---

## After ECU Returns — Execution Contract

1. **Persist `decision_id`** until feedback is sent or the turn is abandoned (lost feedback = no learning signal).
2. **Resolve execution locally:**
   - Use `capability_id` as the **semantic** capability key.
   - Use `provider` as the **implementation** selector inside your adapter layer.
   - Use `execution_type` to choose **transport** (`api` | `mcp` | `function_call`).
3. **If `callable === false`:** Do not assume a direct invoke path exists; escalate (human, different planner step, or richer context) instead of blind tool spam.
4. **Execute** your mapped MCP tool / HTTP client / registered function — WisePick does not perform this step.

---

## ECU Interpretation Rules

| Field | Meaning |
|-------|---------|
| **`capability_id`** | Stable **type** of work (e.g. `audio_transcription`, `image_generation`). Primary key for your **capability → handler** map. Prefer routing on this over raw product names. |
| **`provider`** | **Which implementation** satisfies that capability for this decision (e.g. `feishu_minutes`, `openai`). Select credentials, endpoints, or MCP server routing using this **together with** `capability_id`. |
| **`execution_type`** | Intended **invocation mechanism**: `api` (HTTP/SDK), `mcp` (MCP tool call), `function_call` (in-process function). Your adapter picks the matching executor; WisePick does not invoke it. |
| **`callable`** | **`true`:** Safe to attempt automated execution via your mapped path (subject to your policies). **`false`:** Routing is informational or execution is not assumed safe/direct — avoid brute-force trying tools. |
| **`confidence`** | Router score **reflecting match + stats + bootstrap** (not calibrated probability). Higher → stronger suggestion to use this ECU; still validate constraints locally. |

---

## Mapping ECU → Local MCP / API / Skill

**Pattern:**

```text
(capability_id, provider, execution_type) → local_executor
```

**Example registry (conceptual):**

```json
{
  "audio_transcription": {
    "feishu_minutes": { "execution_type": "api", "invoke": "skills/feishu_transcribe" },
    "tongyi_tingwu": { "execution_type": "api", "invoke": "tools/tingwu_client" }
  }
}
```

**Resolution order (recommended):**

1. Lookup by `capability_id`.
2. Narrow by `provider`.
3. Branch on `execution_type` (REST vs MCP vs function).

**MCP:** Translate to a specific tool name + server config **you** maintain; WisePick does not list MCP tool IDs.

**Skills / plugins:** Bind under `capability_id`; use `provider` for variant-specific parameters.

---

## Calling `/v1/feedback`

**Request:**

```json
{
  "decision_id": "dec_abc123def4567890",
  "success": true,
  "latency_ms": 1200,
  "user_note": "{\"token_usage\": 450, \"cost_usd\": 0.01}"
}
```

**`user_note` (optional string):** Strongly recommended: embed a **JSON object serialized as a string** so execution cost / ROI signals stay structured without any database migration—e.g. token counts, USD spend, or other metrics your runtime already tracks. Example payload shape:

```json
{"token_usage": 450, "cost_usd": 0.01}
```

Serialize that object to a string and send it as `user_note`. Same pattern applies when explaining failures (constraint text plus optional numeric fields). Preserves a machine-readable convention for future ROI-aware routing logic.

**Response:**

```json
{ "ok": true }
```

**Rules:**

- Must reference a **real** `decision_id` from a prior `/v1/decide` response (404 if unknown).
- `success` drives future routing via capability stats.
- `latency_ms` — optional wall-clock signal.
- `user_note` — optional; **prefer** JSON-as-string ROI/cost metadata as above for observability and downstream analytics.

---

## Feedback Loop (Closed Loop)

```text
intent
  → POST /v1/decide
  → receive ECU (store decision_id)
  → map ECU → local execution
  → execute
  → POST /v1/feedback (success/failure + latency)
  → capability_stats updated
  → next POST /v1/decide benefits from execution history
```

**Failure path:** Send `success: false` with optional `user_note` (plain text or JSON string per above) explaining constraint violations — still closes the loop.

---

## Avoid Blind Trial-and-Error

- Do **not** enumerate all tools/MCP resources when `/v1/decide` returns an ECU.
- Do **not** ignore `callable` or low-confidence ECUs by randomly trying alternatives without new context.
- Do **not** skip `/v1/feedback` — it starves the routing signal.
- **Do** narrow search using `capability_id` + `provider` first; **do** add task/context mutations before re-deciding.

---

## Recommended Agent Loop

```text
1. intent(user_task, optional context/constraints)
2. POST /v1/decide
3. parse ECU: decision_id, capability_id, provider, execution_type, callable, confidence
4. if not callable → replan / ask / enrich context → goto 2 (do not tool-spray)
5. map (capability_id, provider, execution_type) → local handler
6. execute handler(task, context)
7. POST `/v1/feedback` with `decision_id`, outcome, optional `latency_ms`, optional `user_note` (ROI JSON string recommended)
8. continue session or goto 1 with updated state
```

---

## Minimal Integration Example (curl → ECU → feedback)

```bash
# 1) Decide
DECISION=$(curl -s -X POST "http://localhost:8000/v1/decide" \
  -H "Content-Type: application/json" \
  -d '{"task":"Summarize this technical document"}')

# Extract fields (example: use jq in shell)
DECISION_ID=$(echo "$DECISION" | jq -r '.decision_id')
CAP=$(echo "$DECISION" | jq -r '.capability_id')
PROV=$(echo "$DECISION" | jq -r '.provider')

# 2) Execute locally (pseudocode — implement in your runtime)
# run_local_capability "$CAP" "$PROV" ...

# 3) Feedback
curl -s -X POST "http://localhost:8000/v1/feedback" \
  -H "Content-Type: application/json" \
  -d "{\"decision_id\":\"$DECISION_ID\",\"success\":true,\"latency_ms\":1200}"
```

---

## Agent Behavior Recommendation

- **Prioritize ECU routing** from `/v1/decide` over ad-hoc product/tool name guessing.
- **Prefer `capability_id` over marketing or product names** when building maps and prompts.
- **Always send `/v1/feedback`** after execution so routing memory (`capability_stats`) improves.
- **Avoid blind tool traversal**; use one ECU path per decision cycle unless `callable` is false or execution proves impossible — then revise **task/context** and call `/v1/decide` again.
- **Treat WisePick as Decision Layer only** — you own MCP/API/skill execution and safety.

---

## Infrastructure Awareness (Optional YantrikDB)

When **`YANTRIK_DB_URL`** is set, WisePick calls **YantrikDB’s** `GET /v1/health` during `/v1/decide` and reads **`replication_lag_log_entries`**. This does **not** change your Supabase/PostgreSQL schema; it is a lightweight, optional plugin.

**Deterministic routing in clusters:** If replication lag (log entries) is **greater than 500**, WisePick applies a **health penalty**: every candidate ECU score is multiplied by **0.5** before ranking. That uniformly lowers **confidence** for all tools for that request, keeping ordering relative to each other while signaling cluster stress.

**When disabled or unreachable:** If `YANTRIK_DB_URL` is empty, or the health request fails, WisePick **skips** this step and uses the standard score only—no errors.

**Agent-visible fields:** `explain.yantrik_cluster` and `trace.yantrik_cluster` include `configured`, `replication_lag_log_entries`, `health_penalty_applied`, and `health_score_multiplier` when relevant.

---

## Quick Reference — Decision Layer Boundary

```json
{
  "wise_pick": ["route", "explain", "persist_decision_id", "learn_from_feedback"],
  "agent_runtime": ["map_ecu", "execute", "enforce_policy", "retry", "secrets"]
}
```
