# AGENTS.md — WisePick Agent Automation Spec

> **Docs:** [Overview](./README.md) | [Integration & SDK](./README_API.md) | [Agent Protocol](./AGENTS.md)

**Audience:** Coding agents, runtime configurators, CI generators (Cursor, Cline, Devin, OpenHands, etc.).

**How to implement (SDK, env, adapters, deploy):** [README_API.md](./README_API.md) only.

**Product overview:** [README.md](./README.md).

**Boundary:** WisePick routes and scores; your runtime discovers, maps, executes, enforces policy, holds secrets and session state. WisePick remains agnostic to whether tools are registered via static manifests or dynamic MCP hosts.

```json
{
  "wise_pick": ["route", "explain", "persist_decision_id", "learn_from_feedback"],
  "agent_runtime": ["map_ecu", "execute", "enforce_policy", "retry", "secrets"]
}
```

---

## WisePick v1 ECU Protocol

HTTP paths remain `v0` (`/v1/decide`, `/v1/feedback`). **v1** denotes the capability-centric ECU payload agents must parse and act on.

### Decide request (agent → WisePick)

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `task` | string | yes | Natural-language intent for this routing cycle |
| `context` | object | no | Opaque key/value; may include `trace_id`, `session_id` for observability correlation |
| `constraints` | object | no | Opaque limits (cost, timeout, region flags, etc.) |

### ECU response (WisePick → agent)

| Field | Type | Required | Semantics |
| --- | --- | --- | --- |
| `decision_id` | string | yes | Persist until `feedback` or turn abandon |
| `capability_id` | string | yes | **What** work to perform—stable semantic type (see below) |
| `provider` | string | yes | **Which** implementation satisfies that capability for this decision |
| `execution_type` | enum | yes | **How** the runtime should invoke locally (see below) |
| `callable` | boolean | yes | `false` → no assumed direct invoke; replan/enrich, do not tool-spray |
| `confidence` | number | yes | Router score (match + stats + bootstrap); not calibrated probability |
| `reason` | string | yes | Human-readable routing explanation |
| `explain` | object | yes | Audit/scoring detail |
| `trace` | object | yes | Timing, candidates, optional `yantrik_cluster` |
| `tool_key` | string | legacy | Mirrors `provider`; ignore for new configs |

### `capability_id` (semantic capability type)

- Stable identifier for a **class of work** (e.g. `audio_transcription`, `translation`, `search_files`).
- Primary lookup key in the agent’s capability registry and in OpenAI `tool_choice.function.name` when hard-routing the first completion.
- Must align with registered tool/MCP `function.name` values the model can call (see auto-config `tool_capability_map`).

### `provider` (implementation selector)

- Names the **vendor/backend** chosen for this `capability_id` (e.g. `feishu_minutes`, `openai`, `deepl`).
- Used **with** `capability_id` to select credentials, base URL, MCP server, or skill variant—not as a substitute for `capability_id`.
- Legacy alias: `tool_key` === `provider`.

### `execution_type` (local transport hint)

| Value | Agent obligation |
| --- | --- |
| `api` | Invoke via HTTP/SDK client owned by the runtime |
| `mcp` | Invoke via MCP tool call on a server the runtime maintains |
| `function_call` | Invoke in-process registered handler |

WisePick does not perform the invocation; the value only selects which executor branch to use after `(capability_id, provider)` resolution.

### Feedback request (agent → WisePick)

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `decision_id` | string | yes | From the ECU that initiated the execution |
| `success` | boolean | yes | Drives `tool_stats.success_rate` |
| `latency_ms` | integer | yes | Wall-clock execution duration (ms), `>= 0` |
| `token_cost` | object | no | `{ "input": int, "output": int }` — token ROI; aggregated as `avg_token_cost` |
| `result_quality` | number | no | `0.0`–`1.0` — subjective or automated quality signal |
| `user_note` | string | no | Free-text only (errors, context); do not embed structured ROI here |

### Closed loop (state machine)

```text
decide → store(decision_id, ecu) → resolve(capability_id, provider, execution_type) → execute → feedback → (next decide)
```

**Prohibited:** full tool/MCP enumeration after ECU; skipping `feedback`; random alternate tools when `callable` is true without new `task`/`context`.

---

## Observability contract (`mcp.route_decision.v1`)

When the API host enables Langfuse (see [README_API.md](./README_API.md#optional-plugins)), decide emits this schema asynchronously. Agents may also log compatible bundles for audit.

```json
{
  "metadata": {
    "schema_version": "mcp.route_decision.v1",
    "decision_id": "dec_abc123def4567890",
    "trace_id": "trace_9876543210abcdef",
    "router_name": "wisepick",
    "capability_id": "audio_transcription",
    "provider": "feishu_minutes",
    "execution_type": "api",
    "callable": true,
    "confidence": 0.87,
    "latency_ms": 450,
    "candidate_count": 1,
    "top_candidates": [
      {
        "rank": 1,
        "capability_id": "audio_transcription",
        "score": 0.87,
        "selected": true
      }
    ],
    "reason_codes": ["capability_match"]
  },
  "output": {
    "capability_id": "audio_transcription",
    "callable": true
  }
}
```

Execution outcomes may emit `mcp.execution_feedback.v1` child spans when feedback is recorded. Correlation: pass `trace_id` / `session_id` in decide `context`.

---

## Auto-Configuration Manifest (`wisepick.agent.v1`)

Agents and scaffolds should emit or consume a single JSON file (e.g. `wisepick.agent.json`) at repo or runtime config root.

```json
{
  "schema": "wisepick.agent.v1",
  "wisepick": {
    "api_base_url": "http://localhost:8000"
  },
  "routing": {
    "enabled": true,
    "hard_route_first_completion": true,
    "release_tool_choice_when_api_call_count_gt": 1
  },
  "tool_capability_map": {
    "<runtime_tool_or_mcp_name>": "<capability_id>",
    "search_files": "search_files",
    "feishu_transcribe": "audio_transcription"
  },
  "capability_registry": {
    "<capability_id>": {
      "execution_type_default": "api",
      "providers": {
        "<provider>": {
          "local_ref": "<handler_id_or_path>",
          "execution_type": "api"
        }
      }
    },
    "audio_transcription": {
      "execution_type_default": "api",
      "providers": {
        "feishu_minutes": { "local_ref": "feishu_transcribe", "execution_type": "api" },
        "tongyi_tingwu": { "local_ref": "tingwu_client", "execution_type": "api" }
      }
    }
  },
  "feedback": {
    "required_after_execution": true,
    "latency_ms_required": true,
    "token_cost": { "input": 1200, "output": 450 },
    "result_quality": 0.92
  }
}
```

| Key | Purpose |
| --- | --- |
| `tool_capability_map` | **Required for OpenAI hard-route:** maps each runtime tool/MCP name to the `capability_id` WisePick may return |
| `capability_registry` | **Required for execution:** resolves `(capability_id, provider, execution_type)` → `local_ref` |
| `routing.hard_route_first_completion` | When true, agent must apply WisePick route only on first LLM completion of a turn |
| `routing.release_tool_choice_when_api_call_count_gt` | When exceeded, agent must not send forced `tool_choice` |
| `feedback.required_after_execution` | When true, agent must POST `/v1/feedback` for every completed ECU path |

Validation rules for automations:

- Every value in `tool_capability_map` must exist as a key in `capability_registry` or be self-mapped (`name` === `capability_id`).
- Every `providers` entry must declare `execution_type` ∈ `api` | `mcp` | `function_call`.
- `api_base_url` must not include path suffixes; client appends `/v1/decide` and `/v1/feedback`.

---

## Agent obligations (checklist)

- Load or generate `wisepick.agent.v1` before enabling routing.
- On each new user turn: `decide` → retain `decision_id` + full ECU.
- If `routing.hard_route_first_completion`: force route only when `api_call_count == 1` (see [README_API.md](./README_API.md#step-4--multi-turn-release-after-the-first-completion)).
- Resolve execution via `capability_registry[capability_id].providers[provider]` using `execution_type`.
- If `callable === false`: do not execute; mutate `task`/`context` and `decide` again.
- After execution: `feedback` with same `decision_id` when `feedback.required_after_execution` is true.

---

## Replay, fork, and idempotency

### `decision_id` (learning anchor)

- One `decision_id` per successful `/v1/decide` for a routing cycle.
- **Must** be sent on `/v1/feedback` for that execution so `capability_stats` updates.
- **Do not** reuse one `decision_id` across unrelated executions.
- On **replan** (new `task`/`context`), call `/v1/decide` again and store the new `decision_id`.

### Fork (multi-branch turns)

- Each branch that makes independent routing choices needs its own `decide` + `decision_id`.
- Forked workers must not share feedback for a parent `decision_id` unless they executed that exact routed ECU.

### Idempotency (execution plane)

WisePick is stateless on the API side; **your runtime** owns idempotent execution keys.

| Runtime profile | Idempotency key | Rules |
| --- | --- | --- |
| **SafeAgent** | `request_id` from `wisepick_to_safeagent_request_id` | Derived from `session_id`, `turn_id`, `start_time_ms`, normalized `task`, `capability_id`, `provider`, `constraints`. **Excludes** WisePick `decision_id` so a fresh decide with the same intent reuses the same SafeAgent slot. Orchestrator must pass stable `start_time_ms` across retries. |
| **ChainWeaver** | Flow run identity (runtime-owned) | WisePick maps `capability_id` → `(flow_id, flow_version)`; ChainWeaver owns flow instance deduplication. |
| **Generic** | Your workflow/run ID | Bind `decision_id` to audit logs; use a separate idempotency key for side-effecting work. |

### Durable execution replay semantics

For durable runtimes (e.g. Aetheris):

- **Record** at route time: `decision_id`, `confidence` (score), `reason_codes`, `capability_id`, `provider`, and ranked candidates when present.
- **Replay:** Rehydrate execution from stored evidence; **do not** call `/v1/decide` again for the same replayed step unless intent or constraints changed.
- **Degradation:** When evidence indicates fallback (`reason_codes` includes `fallback_routing`) or `callable` was false, replay must not assume a direct invoke path.
- **Feedback on replay:** Send `/v1/feedback` only when a **new** execution attempt completes under a **new** `decision_id`; do not double-count outcomes for historical decisions.

Adapter wiring (modules, types): [README_API.md](./README_API.md#runtime-adapters).

---

## Recommended agent loop

```text
1. intent(user_task, optional context/constraints)
2. POST /v1/decide
3. parse ECU: decision_id, capability_id, provider, execution_type, callable, confidence
4. if not callable → replan / ask / enrich context → goto 2 (do not tool-spray)
5. map (capability_id, provider, execution_type) → local handler
6. execute handler(task, context) with runtime idempotency key
7. POST /v1/feedback with decision_id, outcome, latency_ms, optional token_cost / result_quality
8. continue session or goto 1 with updated state
```

---

## Infrastructure signals (read-only)

When the API host enables optional plugins, agents may read:

- `explain.yantrik_cluster` / `trace.yantrik_cluster` — cluster lag penalty applied (scores × 0.5).
- Langfuse-correlated `trace_id` / `session_id` echoed from decide `context`.

Configuration: [README_API.md](./README_API.md#optional-plugins).
