# WisePick API — Builder Integration

WisePick is a stateless decision layer: `POST /v1/decide` → ECU → your runtime executes → `POST /v1/feedback`. It does not run tools.

## Deployment & Production Requirements | 部署与生产环境要求

**Production architecture contract:** WisePick API is the **logical control plane** of your product. In production, you must deploy the WisePick service in your private containers or cloud environment and ensure the Agent runtime can reach that API reliably (stable base URL, health checks, persistence).

**生产环境架构契约：** WisePick API 是您产品的**逻辑中枢**。在生产环境，您必须将 WisePick 服务部署在您的私有容器/云环境中，并确保 Agent 运行时可稳定访问该 API。

**Data sovereignty and evolution:** Collective decision memory and the feedback learning loop depend on **persisted decision records** on your production API host (`DATABASE_URL`). If you do not run a production-grade WisePick API, your product cannot accumulate routing experience across releases.

**关于数据主权与演进：** WisePick 的「集体决策记忆」与「反馈学习闭环」依赖于您生产环境中持久化的 API 决策记录。若未上线生产级 API，您的产品将无法积累任何决策经验。

**Local bootstrap (logic validation only):** Configure `DATABASE_URL` in `.env` (see [.env.example](./.env.example)), then `uvicorn app.main:app --reload`. Smoke: `curl -s http://localhost:8000/health`.

**本地启动（仅逻辑验证）：** 配置 `.env` 中的 `DATABASE_URL` 后运行 `uvicorn`；通过 `/health` 确认服务可用。

Machine-readable contract: [AGENTS.md](./AGENTS.md). Narrative overview: [README.md](./README.md).

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

### Scoring (v0)

```
score = capability_match * 0.70 + execution_success_rate * 0.20 + effective_bootstrap_weight * 0.10
```

### Errors

```json
{ "error": "error_type", "message": "Human-readable description" }
```

---

## Optional plugins

**YantrikDB** (`YANTRIK_DB_URL`, optional `YANTRIK_DB_API_KEY`): On `/v1/decide`, if replication lag > 500 log entries, all candidate scores × 0.5. Empty URL → skipped. Fields: `explain.yantrik_cluster`, `trace.yantrik_cluster`.

**Langfuse** (`WISEPICK_LANGFUSE_PUBLIC_KEY` + `SECRET_KEY`): Background `mcp.route_decision.v1` telemetry. Pass `trace_id` / `session_id` in decide `context` to correlate.

See [.env.example](./.env.example).

---

## ChainWeaver Integration

We provide a native adapter for ChainWeaver that maps ECU decisions directly to FlowExecutor calls. It strictly adheres to the decision-execution separation, ensuring that WisePick only handles the routing logic, while ChainWeaver handles the deterministic execution.

Reference: [`adapters/chainweaver_adapter.py`](./adapters/chainweaver_adapter.py) · [`adapters/chainweaver_adapter_readme.md`](./adapters/chainweaver_adapter_readme.md)

---

## Deploy (Quick Start)

```bash
pip install -r requirements.txt
# configure DATABASE_URL in .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Further adapters:** [examples/](./examples/) · [adapters/chainweaver_adapter.py](./adapters/chainweaver_adapter.py) · [docs/ADAPTER_PATTERN.md](./docs/ADAPTER_PATTERN.md)
