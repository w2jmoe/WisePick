# AGENTS.md — WisePick Agent Automation Spec

**Audience:** Coding agents, runtime configurators, CI generators (Cursor, Cline, Devin, OpenHands, etc.).

**Implementation (client, hooks, `tool_choice`, deploy):** [README_API.md](./README_API.md) only. This file is the machine-readable contract and auto-config schema—not source-level integration steps.

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
| `context` | object | no | Opaque key/value; may include `trace_id`, `session_id` for Langfuse correlation |
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

## Runtime Environment Variables

### Agent / integrator runtime (consumer of WisePick)

| Variable | Required | Default | Role |
| --- | --- | --- | --- |
| `WISEPICK_API_URL` | recommended | `http://localhost:8000` | Base URL for `WisePickClient` / HTTP adapter |
| `WISEPICK_DECIDE_URL` | optional | `{WISEPICK_API_URL}/v1/decide` | Full decide endpoint override (Hermes-style routers) |
| `HERMES_WISEPICK_ROUTING` | optional | `1` | `1`/`true` → enable decide + first-completion injection (Hermes integrations) |
| `WISEPICK_FORCE_TOOL` | optional | — | Test/dry-run: skip HTTP; force tool name (must exist in `tool_capability_map`) |
| `HERMES_WISEPICK_FORCE_TOOL` | optional | — | Hermes alias of `WISEPICK_FORCE_TOOL` |

Set `WISEPICK_API_URL` in deployment manifests; map `tool_capability_map` from the agent’s live tool list before enabling `routing.enabled`.

### WisePick API host (server process)

Not configured by agents. Reference only—see [.env.example](./.env.example) and [README_API.md](./README_API.md#deploy-quick-start).

| Variable | Required on host | Role |
| --- | --- | --- |
| `DATABASE_URL` | yes | PostgreSQL / Supabase for decisions and `capability_stats` |
| `YANTRIK_DB_URL` | no | Cluster health plugin for `/v1/decide` score penalty |
| `YANTRIK_DB_API_KEY` | no | Bearer token for YantrikDB health |
| `WISEPICK_LANGFUSE_PUBLIC_KEY` | no | Telemetry (`mcp.route_decision.v1`) |
| `WISEPICK_LANGFUSE_SECRET_KEY` | no | Telemetry |
| `WISEPICK_LANGFUSE_HOST` | no | Langfuse base URL |
| `WISEPICK_LANGFUSE_OTEL` | no | `true` → OTLP ingestion |
| `WISEPICK_LANGFUSE_ROUTER_NAME` | no | Contract `router_name` (default `wisepick`) |

---

## HTTP Surface

| Method | Path | Role |
| --- | --- | --- |
| GET | `/health` | Liveness |
| POST | `/v1/decide` | Task → ECU |
| POST | `/v1/feedback` | Outcome → learning |

Base URL: value of `WISEPICK_API_URL`.

---

## Optional infrastructure signals

**YantrikDB:** When the API host sets `YANTRIK_DB_URL`, lag `replication_lag_log_entries` > 500 multiplies all candidate scores by `0.5` for that request. Inspect `explain.yantrik_cluster`, `trace.yantrik_cluster`.

**Langfuse:** When keys are set on the host, decide emits `mcp.route_decision.v1` asynchronously. Pass `trace_id` / `session_id` in decide `context` from the agent.

---

## Agent obligations (checklist)

- Load or generate `wisepick.agent.v1` before enabling routing.
- On each new user turn: `decide` → retain `decision_id` + full ECU.
- If `routing.hard_route_first_completion`: force route only when `api_call_count == 1` (see README_API).
- Resolve execution via `capability_registry[capability_id].providers[provider]` using `execution_type`.
- If `callable === false`: do not execute; mutate `task`/`context` and `decide` again.
- After execution: `feedback` with same `decision_id` when `feedback.required_after_execution` is true.

---

## Runtime Adapters

* **ChainWeaver** — **Deterministic Execution Runtime**. [`adapters/chainweaver_adapter.py`](./adapters/chainweaver_adapter.py): `/v1/decide` → explicit `capability_id` → `FlowExecutor.execute_flow`; `/v1/feedback` closes the ROI loop. WisePick owns routing; ChainWeaver owns flow execution.

---

## Durable Execution Integration (e.g., Aetheris)

WisePick supports durable runtimes by treating routing decisions as immutable **Runtime Evidence**.

* **Mechanism**: Use the `AetherisRoutingAdvisor` (see `adapters/aetheris_adapter.py`) to map WisePick responses into audit-ready JSON bundles.
* **Replay Semantics**: Store the `decision_id`, `score`, and `reason_codes` in your execution log. During replay, skip WisePick calls and reuse the stored evidence to ensure deterministic path execution.
* **Failure Mode**: The adapter emits `["fallback_routing"]` for unreachable or low-confidence states, enabling graceful runtime degradation.
