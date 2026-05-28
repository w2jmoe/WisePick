# THYMOS integration (routing advisor artifact)

Experimental contract for discussion: WisePick emits **structured routing evidence**; THYMOS consumes it at the **proposal** stage before governed execution. This is not a runtime adapter and does not transfer orchestration ownership.

Demo: [`examples/thymos_routing_advisor_demo.py`](../../examples/thymos_routing_advisor_demo.py)

## Architecture flow

```text
Intent
  -> WisePick Routing Advisor   (recommend ranked paths, estimates, reason codes)
  -> THYMOS Proposal            (attach evidence, enqueue governance)
  -> Governance / Budget Checks (approve, deny, or require alternative)
  -> Execution                  (invoke approved capability/provider)
  -> Ledger / Replay            (store decision_hash + artifact; rehydrate without re-decide)
```

WisePick stops at the advisor artifact. THYMOS and downstream runtimes own everything after proposal intake.

## Responsibility boundary

| Concern | WisePick | THYMOS |
| --- | --- | --- |
| Capability / provider ranking | Yes (`/v1/decide`, `trace.top_candidates`) | Consumes ranked evidence |
| Confidence, reason codes | Yes | Uses for proposal scoring / audit |
| Cost / latency **estimates** | Advisor artifact (registry-derived or mocked in demo) | Enforces **budget** and SLO policy |
| Retries, fallback **execution** topology | No | Yes (`fail_closed`, `fail_open`, `use_alternative`, `cached_decision`) |
| Tool/MCP invoke, secrets | No | Yes (post-approval) |
| Learning feedback (`/v1/feedback`) | Yes (optional, per execution outcome) | May correlate ledger rows to `decision_id` |

WisePick **recommends paths**. THYMOS **chooses whether and how** to execute them under policy.

## Routing vs governance vs execution

1. **Routing (WisePick)** — Given intent (+ optional `context` / `constraints`), produce a primary ECU and ranked alternatives with scores. Output is advisory JSON (`wisepick.routing_advisor.thymos.v1`), not an execution command.

2. **Governance (THYMOS)** — Proposal stage runs budget ceiling, classification, allowlists, and human approval. May reject the primary path, demand `use_alternative`, or halt (`fail_closed`).

3. **Execution (THYMOS / attached runtime)** — Only after checks pass: dispatch to the approved `(capability_id, provider)`. Retries and compensating actions live here, not in WisePick.

Do not conflate a high routing confidence with an approved execution slot.

## Why alternatives matter

A single winner is insufficient for governed systems:

- **Budget failover** — Promote rank-2 when rank-1 exceeds `cost_estimate_usd` under policy.
- **Provider outage** — `use_alternative` without a new `/v1/decide` when the artifact already encodes ranked paths.
- **Audit** — Ledger stores the full candidate set that informed the proposal.
- **Replay** — Rehydrate the same decision surface from `decision_hash` + serialized artifact.

The demo artifact includes one `selected` candidate and two `alternatives`, each with `capability_id`, `provider`, `score`, and `rank`.

## Replay-safe routing artifacts

Serialize the advisor artifact at proposal time and index by `decision_hash`.

The hash binds stable fields only:

- `schema_version`, normalized `intent`
- `selected` + `alternatives` (capability, provider, score, rank)
- `reason_codes`, `fallback_policy.mode` (+ optional `alternative_rank`)
- `constraints` snapshot

It **excludes** ephemeral `decision_id` so ledger replay can reference the same routing surface even when WisePick mints a new id on a later decide call.

| Field | Replay role |
| --- | --- |
| `decision_hash` | Ledger primary key for routing evidence |
| `decision_id` (in `governance`) | Per-decide audit link to WisePick / Langfuse |
| `fallback_policy.mode` | Documents intended THYMOS behavior (`cached_decision` reuses hash) |

On durable replay, prefer stored artifact + hash; call `/v1/decide` again only when intent or constraints change ([AGENTS.md](../../AGENTS.md#durable-execution-replay-semantics)).

## Fallback policy (THYMOS-owned)

The artifact carries a **hint**; THYMOS implements behavior:

| Mode | Typical use |
| --- | --- |
| `fail_closed` | Deny execution if primary path fails checks or invoke |
| `fail_open` | Allow degraded handler after logged policy exception |
| `use_alternative` | Promote `alternatives[n]` by rank on primary failure |
| `cached_decision` | Rehydrate prior artifact by `decision_hash` without re-routing |

WisePick does not execute these modes.

## Artifact schema (demo)

`wisepick.routing_advisor.thymos.v1` fields:

| Field | Description |
| --- | --- |
| `schema_version` | Artifact contract id |
| `decision_hash` | SHA-256 of stable preimage (replay key) |
| `selected` | Primary `{ capability_id, provider, score, rank }` |
| `confidence` | Router score for selected path |
| `reason_codes` | e.g. `capability_match`, `fallback_routing` |
| `latency_estimate_ms` | Non-binding estimate for proposal budgeting |
| `cost_estimate_usd` | Non-binding estimate for proposal budgeting |
| `alternatives` | Ranked alternates (demo: two entries) |
| `fallback_policy` | THYMOS execution-topology hint |
| `governance` | Audit metadata (`decision_id`, `callable`, `constraint_snapshot`, `replay_key`) |

## Local demo

```bash
python examples/thymos_routing_advisor_demo.py
```

Prints: (1) intent, (2) routing artifact JSON, (3) example `thymos.proposal.v1` input. Stdlib only; no API server.

## Related references

- Aetheris evidence pattern: [`adapters/aetheris_adapter.py`](../../adapters/aetheris_adapter.py) (`AetherisRoutingAdvisor`)
- SafeAgent execution idempotency: [`docs/integrations/safeagent.md`](./safeagent.md)
- Agent ECU contract: [AGENTS.md](../../AGENTS.md)
- Adapter roles: [docs/ADAPTER_PATTERN.md](../ADAPTER_PATTERN.md)
