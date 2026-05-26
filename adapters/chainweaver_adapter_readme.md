# ChainWeaver x WisePick Adapter

Bridge WisePick’s **decision plane** (routing, scoring, feedback) with ChainWeaver’s **execution plane** (`FlowRegistry` + `FlowExecutor.execute_flow`). Stdlib + in-repo `wisepick` client only.

Implementation: [`chainweaver_adapter.py`](./chainweaver_adapter.py)

---

## Installation

```bash
# Clone this adapter repo alongside your project
git clone https://github.com/w2jmoe/chainweaver-wisepick-adapter.git

# Ensure your project can import wisepick (e.g., via PYTHONPATH or pip install)
export PYTHONPATH=$PYTHONPATH:$(pwd)/chainweaver-wisepick-adapter

```

---

## Why use this adapter?

| Layer | Responsibility |
| --- | --- |
| **WisePick** | Turns natural-language intent into one ECU: `capability_id`, `provider`, `confidence`, `decision_id`. Learns from `/v1/feedback`. |
| **ChainWeaver** | Runs a **registered** flow deterministically via `flow_id`—no LLM inside the executor. |
| **This adapter** | Maps ECU → `flow_id` (+ advisory `flow_version`), calls `execute_flow`, then posts structured feedback so the next route benefits from real execution cost and logs. |

Without the adapter, teams re-implement the same glue: decide → guess flow name → execute → forget to feedback. Here that loop is one call: `select_and_execute`.

**Design principle:** **decision is decoupled from execution.** WisePick never discovers tools; ChainWeaver never scores intent. The mapping table is the only coupling surface.

---

## Quick Start

**Prerequisites:** WisePick API running (`uvicorn app.main:app`), ChainWeaver flows registered in your process.

```python
from chainweaver import Flow, FlowExecutor, FlowRegistry
from wisepick import WisePickClient
from chainweaver_adapter import FlowRouteMapping, WisePickChainWeaverAdapter

registry = FlowRegistry()
registry.register_flow(my_flow)

executor = FlowExecutor(registry=registry)
for tool in my_tools:
    executor.register_tool(tool)

adapter = WisePickChainWeaverAdapter(
    wisepick=WisePickClient("http://localhost:8000"),
    registry=registry,
    executor=executor,
    capability_to_flow={
        "audio_transcription": FlowRouteMapping(
            flow_id="transcribe_v2",
            flow_version="2.1.0",
        ),
    },
)

result = adapter.select_and_execute("Transcribe today's standup recording")
print(result["contract"]) 
print(result["execution"])
print(result["trace"])

```

Run unit tests:

```bash
python -m pytest tests/test_chainweaver_adapter.py -q

```

---

## Explicit mapping table (required)

There is **no** fallback `capability_id → same-named flow`. Every capability WisePick can return must appear in `capability_to_flow`:

```python
capability_to_flow = {
    "audio_transcription": FlowRouteMapping(
        flow_id="transcribe_v2",        # FlowRegistry name — sole execution target
        flow_version="2.1.0",           # advisory audit metadata only (see below)
    ),
}

```

**`flow_version` is advisory audit metadata, not an execution selector.** ChainWeaver resolves flows by `flow_id` via `FlowRegistry.get_flow` / `execute_flow(flow_id, …)`. The version string is copied into `WeaverRouterContract`, `initial_input`, and feedback JSON for rollout tracking and observability—it does **not** switch runtime behavior unless your own ChainWeaver layer chooses to read it.

---

## Contract & Trace

* `WeaverRouterContract`: `flow_id` (execution target), `flow_version` (audit-only), `confidence`, `reasoning`.
* Feedback: Sends `/v1/feedback` with JSON note `mcp.chainweaver_execution.v1` containing ChainWeaver trace fields (`trace_id`, `total_duration_ms`, `cost_report`, `execution_log`, etc.).

---

## References

* WisePick runtime pattern: [`./docs/ADAPTER_PATTERN.md`](https://github.com/w2jmoe/WisePick/blob/main/docs/ADAPTER_PATTERN.md)
