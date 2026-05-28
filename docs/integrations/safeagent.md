# SafeAgent integration

WisePick and SafeAgent split **routing** from **durable, idempotent execution**. This document describes the contract implemented in [`adapters/safeagent_adapter.py`](../../adapters/safeagent_adapter.py) and demonstrated in [`examples/safeagent_replay_demo.py`](../../examples/safeagent_replay_demo.py).

## Responsibility split

| Layer | Owns | Does not own |
| --- | --- | --- |
| **WisePick** | `POST /v1/decide` ECU (`capability_id`, `provider`, `execution_type`, `callable`, `decision_id`, scores) | Tool invocation, retries, secrets, session memory |
| **SafeAgent** | Execution dispatch, deduplication by `request_id`, replay/skip semantics | Capability selection, provider choice, learning aggregates |
| **Adapter** (`SafeAgentAdapter`) | ECU → dispatch payload, deterministic `request_id`, `/v1/feedback` closure | SafeAgent runtime internals |

WisePick answers *what* and *which provider* for this routing cycle. SafeAgent answers *whether this logical work already ran* for a stable idempotency key.

## Identifiers

### `decision_id` (WisePick)

- Minted on every successful `/v1/decide`.
- Required on `/v1/feedback` for the execution tied to that ECU.
- **Not** included in the SafeAgent `request_id` preimage.
- On orchestrator retry, a new `decide` typically yields a **new** `decision_id` even when intent is unchanged.

Use `decision_id` for audit trails, Langfuse correlation (`mcp.route_decision.v1`), and per-attempt learning feedback.

### `request_id` (SafeAgent)

- Derived by `wisepick_to_safeagent_request_id()` from:

  `session_id`, `turn_id`, `start_time_ms`, normalized `task`, `capability_id`, `provider`, `constraints`

- Stable when those fields are stable across retries.
- SafeAgent treats `request_id` as the idempotency key: duplicate dispatch with the same key should **SKIP** side-effecting work and return a prior outcome reference.

Orchestrators must pass the same `start_time_ms` (turn anchor) on every retry for a given user turn. If `start_time_ms` drifts, `request_id` changes and SafeAgent will not deduplicate.

### `task_fingerprint` (observability only)

- Used in benchmark instrumentation (`benchmark/instrumentation/wisepick_bench.py`): SHA-256 of normalized task text.
- Correlates logs and bench rows; **not** the SafeAgent idempotency key.
- Differs from `request_id`, which also binds session, turn, capability, provider, constraints, and turn anchor.

Do not conflate `task_fingerprint` with `request_id`. Two turns with the same task string must not share a `request_id` unless session/turn anchor and routing fields align.

## Request flow

```text
orchestrator
  ├─ POST /v1/decide          → ECU + decision_id
  ├─ ecu_to_dispatch_request  → request_id + SafeAgent payload
  ├─ runtime.execute          → RUN (first) | SKIP (duplicate request_id)
  └─ POST /v1/feedback        → decision_id for this attempt (when execution completes)
```

`SafeAgentAdapter.select_and_execute()` performs decide → dispatch → execute → feedback in one call. Production agents may call `route()` and `ecu_to_dispatch_request()` separately for clearer retry boundaries.

## Replay semantics

### Orchestrator retry (same turn, transient failure)

1. First attempt: `decide` → `dec_001` → execute with `request_id` **R** → SafeAgent **RUN**.
2. Retry after failure: `decide` again → `dec_002` (new) → dispatch still yields **R** when turn anchor and intent are unchanged.
3. Second execute: SafeAgent sees **R** already completed → **SKIP** (no duplicate side effects).

WisePick may record separate feedback for `dec_002` if your policy attributes outcomes per decide attempt. Do not double-count historical decisions when rehydrating from durable evidence without a new execution (see [AGENTS.md](../../AGENTS.md#durable-execution-replay-semantics)).

### Durable replay (workflow rehydration)

- Rehydrate from stored ECU + execution evidence; **do not** call `/v1/decide` again for the same replayed step unless intent or constraints changed.
- When evidence shows `callable=false` or fallback routing, replay must not assume a direct invoke path.
- Send `/v1/feedback` only when a **new** execution completes under a **new** `decision_id`; avoid duplicate stats for historical decisions.

### What changes `request_id`

| Change | Effect |
| --- | --- |
| New `turn_id` or `session_id` | New `request_id` |
| Different normalized `task` | New `request_id` |
| Different `capability_id` / `provider` after replan | New `request_id` |
| Different `constraints` | New `request_id` |
| Different `start_time_ms` (turn anchor) | New `request_id` |
| New `decision_id` only | **Unchanged** `request_id` |

## Dispatch payload

`ecu_to_dispatch_request()` emits `mcp.safeagent_execution.v1`-aligned fields, including:

- `request_id`, `startTime_ms`, `decision_id`
- `capability_id`, `provider`, `execution_type`, `callable`, `confidence`
- `task`, `reason`

Feedback `user_note` may embed the same schema for ROI tracing (`SafeAgentAdapter._build_feedback_user_note`).

## Local demo

No running API required:

```bash
python examples/safeagent_replay_demo.py
```

The demo uses `StubSafeAgentRuntime` plus an in-file idempotent wrapper that models production **SKIP** behavior. It prints `decision_id`, `request_id`, first **RUN**, replay **SKIP**, and deterministic equality checks.

## Related references

- Adapter implementation: [`adapters/safeagent_adapter.py`](../../adapters/safeagent_adapter.py)
- Agent replay/idempotency tables: [AGENTS.md](../../AGENTS.md#replay-fork-and-idempotency)
- Runtime adapter overview: [README_API.md](../../README_API.md#safeagent)
- Pattern: [docs/ADAPTER_PATTERN.md](../ADAPTER_PATTERN.md)
