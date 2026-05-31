# WisePick API — Builder Integration

> **Docs:** [Overview](./README.md) | [Integration & SDK](./README_API.md) | [Agent Protocol](./AGENTS.md)

**WisePick Decision API (WPDA)** is a stateless capability routing / decision layer: `POST /v1/decide` → ECU → your runtime executes → `POST /v1/feedback`. It does not run tools or own orchestration.

**Agent protocol & runtime behavior:** [AGENTS.md](./AGENTS.md) only. **Product overview:** [README.md](./README.md).

---

## Deployment & Production Requirements | 部署与生产环境要求

**Production architecture contract:** Deploy **WPDA** as your product’s **routing decision service** (not a task orchestrator). In production, run the WisePick API in your private containers or cloud environment and ensure the agent runtime can reach it reliably (stable base URL, health checks, persistence).

**生产环境架构契约：** 将 **WPDA** 作为产品的**路由决策服务**部署（非任务编排引擎）。在生产环境，您须将 WisePick 服务部署在私有容器/云环境中，并确保 Agent 运行时可稳定访问该 API。

**Data sovereignty and evolution:** Execution feedback and the learning loop depend on **persisted decision records** on your WPDA host (`DATABASE_URL`). That store is the on-ramp to collective decision memory; the long-term **Execution Experience Network** vision is evolutionary—not a separate product you deploy today.

**关于数据主权与演进：** 执行反馈与学习闭环依赖您 WPDA 生产环境中的持久化决策记录。该存储是集体决策记忆的起点；长期**执行经验网络**愿景为演进方向，而非当前需单独部署的网络产品。

**Local bootstrap (logic validation only):** Configure `DATABASE_URL` in `.env` (see [.env.example](./.env.example)), then `uvicorn app.main:app --reload`. Smoke: `curl -s http://localhost:8000/health`.

**本地启动（仅逻辑验证）：** 配置 `.env` 中的 `DATABASE_URL` 后运行 `uvicorn`；通过 `/health` 确认服务可用。

---

## 15-Minute Integration Checklist

Wire [`wisepick/client.py`](./wisepick/client.py) into your Agent completion path and tool-execution hook. No extra client dependencies (stdlib `urllib` only).

### Step 1 — Client bootstrap

```python
from wisepick import WisePickClient

wp = WisePickClient(api_url="http://localhost:8000")  # deployed host in prod
```

Keep one instance per process (or per session factory). Point `api_url` at your self-hosted WisePick base (no trailing slash required).

### Step 2 — Hard-route the first LLM completion

Call `inject_openai_choice` **immediately before** the first provider `chat.completions` (or compatible) request for the turn. It POSTs `/v1/decide` and, when ECU is valid, sets OpenAI-shaped `tool_choice` from `capability_id`.

```python
user_task = "Transcribe today's meeting audio"
api_kwargs = {
    "model": "gpt-4o-mini",
    "messages": messages,
    "tools": openai_tools,  # required: inject is a no-op without tools
}

api_call_count = 0  # per user turn / replan cycle

def build_completion_kwargs() -> dict:
    global api_call_count
    api_call_count += 1
    kwargs = dict(api_kwargs)
    if api_call_count == 1:
        wp.inject_openai_choice(kwargs, user_task)
    return kwargs

# first completion only — tool_choice may be present
response = openai_client.chat.completions.create(**build_completion_kwargs())
```

Persist ECU once per turn if you need `decision_id` for feedback without a second decide (optional):

```python
ecu = wp.decide(user_task)
# then Step 2 inject still works; or set tool_choice manually from ecu["capability_id"]
```

`inject_openai_choice` skips injection when `callable` is `false`, `capability_id` is empty, or `tools` is missing.

### Step 3 — Name alignment (`function.name` ↔ `capability_id`)

`tool_choice.function.name` must equal an entry in `tools[].function.name`. WisePick ranks by **`capability_id`** (semantic capability), not marketing product names.

| OpenAI / MCP `function.name` | WisePick `capability_id` | Local handler |
| --- | --- | --- |
| `audio_transcription` | `audio_transcription` | `transcribe_audio(provider, …)` |
| `search_files` | `search_files` | MCP tool `search_files` |

Note that this protocol alignment holds true regardless of how tools are gathered. WisePick decouples routing from discovery; your runtime can load tools statically or query an MCP server dynamically, but it must map those discovered payloads to stable `capability_id` strings before hitting the decision layer.
请注意，无论工具是如何加载的，此协议对齐均有效。智选将路由与发现解耦：您的运行时可以静态加载工具，也可以动态查询 MCP 服务，但在进入决策层之前，必须将这些发现的能力映射为稳定的 `capability_id` 字符串。

**Rule:** Register tools under **`capability_id` strings** WisePick emits. Use `provider` + `execution_type` inside your executor to pick credentials, endpoint, or MCP server—not as the forced function name.

```python
EXECUTORS = {
    "audio_transcription": lambda provider, task: run_transcribe(provider, task),
    "search_files": lambda provider, task: mcp_call("search_files", task),
}

def run_tool(ecu: dict, task: str):
    fn = EXECUTORS.get(ecu["capability_id"])
    if not fn:
        raise ValueError(ecu["capability_id"])
    return fn(ecu["provider"], task)
```

Mismatch → model cannot call the forced function → fall back to Step 4 or fix the registry.

### Step 4 — Multi-turn: release after the first completion

WisePick routing applies to **turn entry** (first completion). Later completions in the same turn should not keep a forced tool.

```python
def build_completion_kwargs() -> dict:
    global api_call_count
    api_call_count += 1
    kwargs = dict(api_kwargs)
    if api_call_count == 1:
        wp.inject_openai_choice(kwargs, user_task)
    else:
        kwargs.pop("tool_choice", None)  # api_call_count > 1: model picks freely
    return kwargs
```

Reset `api_call_count = 0` (and drop cached `ecu`) on new user intent or explicit replan.

### Step 5 — Feedback on the execution hook

After your tool/MCP handler finishes (success or failure), call `feedback` with the `decision_id` from the turn’s ECU.

```python
def on_tool_finished(ecu: dict, *, ok: bool, err: str | None = None):
    did = ecu.get("decision_id")
    if not did:
        return
    wp.feedback(
        did,
        success=ok,
        latency_ms=latency_ms,
        error_message=err,
        token_usage={"input": 1200, "output": 450},
        result_quality=0.92 if ok else None,
    )

# success path (after local execute)
on_tool_finished(ecu, ok=True, latency_ms=1200)

# failure path
on_tool_finished(ecu, ok=False, latency_ms=300000, err="timeout after 300s")
```

Skipping feedback disables learning for that decision.

**Closed loop:** `decide` → execute mapped handler → `feedback` → `capability_stats` updates next `decide`.

---

## HTTP Surface (reference)

| Method | Path | Role |
| --- | --- | --- |
| GET | `/health` | Liveness |
| POST | `/v1/decide` | Task → ECU |
| POST | `/v1/feedback` | Outcome → stats |

### POST `/v1/decide`

```json
{
  "task": "Summarize this technical document",
  "context": { "language": "Chinese" },
  "constraints": { "max_cost": 10.0, "timeout_seconds": 300 }
}
```

**ECU fields (integrate against these):** `decision_id`, `capability_id`, `provider`, `execution_type` (`api` | `mcp` | `function_call`), `callable`, `confidence`, `reason`, `explain`, `trace`. Legacy `tool_key` mirrors `provider`.

### POST `/v1/feedback`

```json
{
  "decision_id": "dec_abc123def4567890",
  "success": true,
  "latency_ms": 1200,
  "token_cost": { "input": 1200, "output": 450 },
  "result_quality": 0.92,
  "user_note": "optional free-text error or context"
}
```

`latency_ms` is required. Use `token_cost` and `result_quality` for ROI aggregates (`avg_token_cost`, `avg_result_quality`); do not embed them in `user_note`.

### Errors

```json
{ "error": "error_type", "message": "Human-readable description" }
```

---

## Environment variables

See [.env.example](./.env.example) for the full list.

### Agent / integrator runtime (consumer of WisePick)

| Variable | Required | Default | Role |
| --- | --- | --- | --- |
| `WISEPICK_API_URL` | recommended | `http://localhost:8000` | Base URL for `WisePickClient` / HTTP adapter |
| `WISEPICK_DECIDE_URL` | optional | `{WISEPICK_API_URL}/v1/decide` | Full decide endpoint override (Hermes-style routers) |
| `HERMES_WISEPICK_ROUTING` | optional | `1` | `1`/`true` → enable decide + first-completion injection (Hermes integrations) |
| `WISEPICK_FORCE_TOOL` | optional | — | Test/dry-run: skip HTTP; force tool name (must exist in `tool_capability_map`) |
| `HERMES_WISEPICK_FORCE_TOOL` | optional | — | Hermes alias of `WISEPICK_FORCE_TOOL` |

Set `WISEPICK_API_URL` in deployment manifests; map `tool_capability_map` from the agent’s live tool list before enabling routing (see [AGENTS.md](./AGENTS.md) `wisepick.agent.v1`).

### WisePick API host (server process)

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

## How it works (implementation)

### Capability matching | 能力匹配

Task text → capability labels derived from bootstrap rules (`api_tool_specs`).

```text
task → capabilities
```

### Capability scoring | 能力评分

```text
score =
  capability_match       * 0.40  (semantic match)
  execution_success_rate * 0.20  (historical reliability)
  efficiency_factor      * 0.20  (avg_latency_ms, cohort-normalized)
  economy_factor         * 0.10  (avg_token_cost, cohort-normalized)
  bootstrap_weight       * 0.10  (cold-start prior)
```

Legacy v0 blend (when ROI dimensions are sparse):

```text
score = capability_match * 0.70 + execution_success_rate * 0.20 + effective_bootstrap_weight * 0.10
```

### Feedback loop | 反馈闭环

```text
decision → execution → feedback → capability_stats → next decision
```

### Components | 核心组件

```text
Routing Core (decision_engine)     — task → ECU scoring and selection
Capability Registry (api_tool_specs) — providers, labels, bootstrap weights
Execution Memory (tool_stats)      — success rate, latency, token ROI from feedback
```

---

## Optional plugins

**YantrikDB** (`YANTRIK_DB_URL`, optional `YANTRIK_DB_API_KEY`): On `/v1/decide`, reads YantrikDB `/v1/health`. If `replication_lag_log_entries` > 500, all candidate scores × 0.5 for that request. Empty URL → skipped. Inspect `explain.yantrik_cluster`, `trace.yantrik_cluster`. No primary schema change.

**Langfuse** (`WISEPICK_LANGFUSE_PUBLIC_KEY` + `WISEPICK_LANGFUSE_SECRET_KEY`): Background export of `mcp.route_decision.v1` (and execution feedback spans when configured). Pass `trace_id` / `session_id` in decide `context` to correlate. Does not add request latency on the hot path.

Telemetry payload shape for observability tools: [AGENTS.md](./AGENTS.md#observability-contract-mcproute_decisionv1).

---

## Runtime adapters

Thin bridges: WisePick `decide` / `feedback`; your runtime executes. Pattern: [docs/ADAPTER_PATTERN.md](./docs/ADAPTER_PATTERN.md).

### ChainWeaver

Maps ECU → `FlowExecutor.execute_flow`; explicit `capability_id` → `(flow_id, flow_version)` table only.

- Module: [`adapters/chainweaver_adapter.py`](./adapters/chainweaver_adapter.py)
- Types: `ChainWeaverAdapter`, `RoutingDecision` (`flow_id`, `flow_version`, `confidence`, `reasoning`)
- Entry: `select_and_execute(user_request)` or `route()` for decide-only

### SafeAgent

Maps ECU → idempotent `request_id` + SafeAgent `runtime.execute`; closes feedback with ROI `user_note`.

- Module: [`adapters/safeagent_adapter.py`](./adapters/safeagent_adapter.py)
- Types: `SafeAgentAdapter`, `SafeAgentRoutingDecision`
- Requires `session_id`, `turn_id` (and orchestrator `start_time_ms` for distributed idempotency)

### Aetheris (experimental)

Maps `DecideResponse` → `AetherisRouteEvidence` for durable evidence stores (no HTTP in adapter).

- Module: [`adapters/aetheris_adapter.py`](./adapters/aetheris_adapter.py)
- Type: `AetherisRoutingAdvisor` → `to_evidence()`
- Replay semantics (skip re-decide on replay): [AGENTS.md](./AGENTS.md#durable-execution-replay-semantics)

### THYMOS (OpenThymos)

Maps ECU → `RoutingEvidence`; attaches `routing_evidence` on outer `Proposal` per OpenThymos Proposal Contract v1 Option 2 (outside `ProposalBody`; no HTTP in adapter).

- Module: [`adapters/thymos_adapter.py`](./adapters/thymos_adapter.py)
- Types: `FallbackHint`, `RoutingEvidence`, `ThymosRoutingAdvisor`
- Entry: `ThymosRoutingAdvisor(...).to_evidence()` then `attach_routing_evidence_to_proposal(proposal_envelope, evidence)`

### Examples

[examples/wisepick_router.py](./examples/wisepick_router.py) · [examples/omnicore_adapter.py](./examples/omnicore_adapter.py)

---

## Deploy (Quick Start)

```bash
pip install -r requirements.txt
# configure DATABASE_URL in .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
