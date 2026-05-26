# Runtime adapter pattern

## Roles

**WisePick** is a stateless **decision layer**: `POST /v1/decide` returns one ECU (`capability_id`, `provider`, `execution_type`, `callable`, `confidence`, `decision_id`). It does not run tools, hold session memory, or store secrets.

**Your runtime** keeps **execution ownership**: HTTP/MCP/SDK calls, retries, idempotency, policy, and side effects. It also keeps **credential ownership** (API keys, OAuth, VPC endpoints) and **memory ownership** (conversation state, plans, RAG caches). WisePick only needs the task string (plus optional `context` / `constraints`) per decide call.

## Why an adapter instead of forking the runtime

Forking duplicates orchestration, transport, and observability stacks you already maintain. A **routing adapter** is a thin boundary:

1. Call `/v1/decide` when you would otherwise pick a tool or capability heuristically.
2. Map `(capability_id, provider, execution_type)` to a local handler (existing registry).
3. Call `/v1/feedback` after the handler finishes (success or failure).

You change **where the route comes from**, not **how the runtime runs**. No requirement to replace memory systems, workflow engines, or auth.

## Why you do not redesign memory / orchestration / credentials

WisePick does not prescribe tool schemas, MCP layouts, or planner graphs. It emits a stable ECU-shaped decision your adapter interprets. Session continuity stays in your store; secrets stay in your vault; multi-step flows stay in your scheduler. The adapter only synchronizes **routing intent** and **post-hoc outcomes** (`decision_id` → feedback).

## Reference material

- Narrative contract: [AGENTS.md](../AGENTS.md)
- Copy-paste sketches: [examples/](../examples/) — [wisepick_router.py](../examples/wisepick_router.py), [omnicore_adapter.py](../examples/omnicore_adapter.py)
- ChainWeaver: [adapters/chainweaver_adapter.py](../adapters/chainweaver_adapter.py) — guide: [chainweaver_adapter_readme.md](../adapters/chainweaver_adapter_readme.md)
