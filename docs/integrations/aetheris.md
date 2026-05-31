# WisePick × Aetheris — External Interoperability Proposal

> **Classification:** External Interoperability Proposal (EIP)
> **Scope:** `AetherisRouteEvidence` artifact, produced by `adapters/aetheris_adapter.py`
> **Principle:** Routing proposes. Authorization decides. PEP enforces.

WisePick is a stateless capability-routing layer. It does not make authorization decisions, hold credentials, or invoke tools. This document describes the narrow `AetherisRouteEvidence` artifact — the only surface WisePick exposes to Aetheris — and its relationship to Aetheris's policy engine and PEP enforcement boundary.

---

## 1. Artifact definition — `AetherisRouteEvidence` JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "wisepick.aetheris_route_evidence.v1",
  "type": "object",
  "required": [
    "decision_id",
    "selected_capability",
    "candidate_list",
    "score_bps",
    "reason_codes"
  ],
  "additionalProperties": false,
  "properties": {
    "decision_id": {
      "type": "string",
      "minLength": 1,
      "description": "Opaque WisePick routing cycle identifier. Audit correlation key only."
    },
    "selected_capability": {
      "type": "string",
      "pattern": "^[a-z0-9_]+$",
      "description": "Normalized capability_id (strip + lower). Never a PEP input."
    },
    "candidate_list": {
      "type": "array",
      "items": { "type": "string", "pattern": "^[a-z0-9_/]+$" },
      "description": "Ranked normalized capability/provider labels from trace.top_candidates."
    },
    "score_bps": {
      "type": "integer",
      "minimum": 0,
      "maximum": 10000,
      "description": "WisePick confidence in basis points (0–10 000). Integer only; no float."
    },
    "reason_codes": {
      "type": "array",
      "items": {
        "type": "string",
        "enum": ["capability_match", "fallback_routing"]
      },
      "minItems": 1,
      "description": "Structured routing rationale. Does not encode authorization status."
    }
  }
}
```

**Type constraints:**

| Field | Wire type | Encoding rule |
| --- | --- | --- |
| `decision_id` | `string` | Opaque; preserved verbatim from WisePick response |
| `selected_capability` | `string` | `capability_id.strip().lower()` |
| `candidate_list` | `string[]` | Each label: `capability_id.strip().lower()` (preferred) or `provider.strip().lower()` |
| `score_bps` | `integer` | `round(confidence × 10 000)`; clamped to `[0, 10 000]`; **no float on wire** |
| `reason_codes` | `string[]` | Closed enum; derived from routing signals only |

---

## 2. Concrete payload example

The following artifact is produced by `AetherisRoutingAdvisor` from a live WisePick ECU with `confidence = 0.75`.

```json
{
  "decision_id": "dec_aetheris_demo_001",
  "selected_capability": "audio_transcription",
  "candidate_list": [
    "audio_transcription",
    "tongyi_tingwu"
  ],
  "score_bps": 7500,
  "reason_codes": [
    "capability_match"
  ]
}
```

This object is the complete artifact. No additional fields are added; no float values are present.

---

## 3. Hashing and normalization — `decision_hash`

> `decision_hash` is an **optional audit-correlation digest**. It is not a field on `AetherisRouteEvidence` itself; it is computed by the consumer (e.g., an audit store or replay verifier) from the evidence payload. WisePick does not compute or transmit it.

### 3.1 Normalization rules (applied before hashing)

All string fields are normalized at construction time by `adapters/utils.py`:

```
normalize_route_token(value) = value.strip().lower()
```

This is applied to `capability_id` and `provider` before they are placed in `selected_capability` or `candidate_list`. The result is a byte-stable string under any UTF-8 encoding on any platform.

`score_bps` is derived from the WisePick `confidence` float at the **adapter boundary** only:

```
score_bps = clamp(round(confidence × 10_000), 0, 10_000)
```

Once on the wire as `integer`, no float operations are performed.

### 3.2 Canonical preimage construction

A consumer wishing to derive `decision_hash` from the artifact MUST:

1. Collect the five required fields: `decision_id`, `selected_capability`, `candidate_list`, `score_bps`, `reason_codes`.
2. Sort `reason_codes` lexicographically (for determinism across producers).
3. Serialize to canonical JSON: **sorted keys**, no insignificant whitespace, UTF-8.
4. Compute SHA-256 over the UTF-8 bytes.

```python
import hashlib, json

def compute_decision_hash(evidence: dict) -> str:
    preimage = {
        "decision_id":        evidence["decision_id"],
        "selected_capability": evidence["selected_capability"],
        "candidate_list":     evidence["candidate_list"],
        "score_bps":          int(evidence["score_bps"]),
        "reason_codes":       sorted(evidence["reason_codes"]),
    }
    canonical = json.dumps(preimage, sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

**Verified example** — applying the above to the payload in §2:

```
preimage (canonical JSON):
  {"candidate_list":["audio_transcription","tongyi_tingwu"],
   "decision_id":"dec_aetheris_demo_001",
   "reason_codes":["capability_match"],
   "score_bps":7500,
   "selected_capability":"audio_transcription"}

SHA-256:
  306b3c59d4eb15efac1f31cb3dda6454538e442f423a366d950b7008946debaa
```

### 3.3 Determinism guarantee

The following values are **excluded** from the preimage:

- WisePick-internal timing or trace metadata (`latency_ms`, `trace_id`).
- `callable` (behavioral flag, not routing identity).
- Any field not present in `AetherisRouteEvidence`.

Exclusions ensure the hash is stable across retries where WisePick may mint a new `decision_id` variant or re-score with minor latency differences.

---

## 4. Audit metadata declaration

`decision_hash` is **audit metadata only**.

| Property | Value |
| --- | --- |
| Purpose | Ledger correlation; replay verification |
| Authorization input | **No** — MUST NOT be read by any PEP or policy engine |
| Trust level | Untrusted producer metadata; treat as advisory |
| Writability | Read-only from Aetheris's perspective; computed, never signed by WisePick |

The `AetherisRouteEvidence` artifact as a whole is similarly scoped:

> WisePick's routing output is a **recommendation** about which capability to invoke. It carries no Writ, no Ed25519 signature, and no authorization grant. Aetheris's policy engine evaluates authorization independently of whether WisePick was consulted at all.

Implementations MUST treat the absence of `AetherisRouteEvidence` on a request as equivalent to its presence with `reason_codes: ["fallback_routing"]` — the authorization path is unchanged either way.

---

## 5. Architectural independence — routing proposal vs PEP enforcement

```
┌─────────────────────────────┐
│       Agent / Runtime       │
│                             │
│  1. POST /v1/decide         │
│     ↓  ECU (advisory)       │
│  2. AetherisRoutingAdvisor  │
│     .to_evidence()          │
│     ↓  AetherisRouteEvidence│
│     (non-authoritative)     │
└────────────┬────────────────┘
             │  attach as non-authoritative metadata
             ▼
┌─────────────────────────────┐
│     Aetheris Request        │
│  ┌──────────────────────┐   │
│  │  routing_evidence    │   │  ← read by audit/observability only
│  │  (advisory, opaque)  │   │
│  └──────────────────────┘   │
│  ┌──────────────────────┐   │
│  │  AuthorizationV1     │   │  ← sole authority path
│  │  (Writ, Policy,      │   │
│  │   Budget, PEP)       │   │
│  └──────────────────────┘   │
└─────────────────────────────┘
             │
             ▼
┌─────────────────────────────┐
│  Policy Engine              │
│  Input: Intent, Writ, World │
│  Output: Permit / Deny /    │
│          RequireApproval    │
│                             │
│  ← routing_evidence is      │
│    never passed here        │
└─────────────────────────────┘
             │ Permit
             ▼
┌─────────────────────────────┐
│  PEP (ToolContract invoke)  │
│  Scope: Writ-declared only  │
└─────────────────────────────┘
```

**Physical isolation properties:**

1. `AetherisRoutingAdvisor` does not call Aetheris's policy engine or any Writ-resolution path.
2. `AetherisRouteEvidence` is constructed from a WisePick `DecideResponse` alone; it has no dependency on `WorldState`, `WritId`, or `PolicyTrace`.
3. The adapter module (`adapters/aetheris_adapter.py`) imports nothing from Aetheris's authorization stack; the dependency edge is one-way and read-only at the ECU level.
4. If WisePick is unavailable, the adapter returns no evidence; Aetheris continues to process the request through its normal authorization path without degradation.

---

## 6. Attaching routing evidence as non-authoritative metadata

The following pseudocode shows the correct attachment pattern. `routing_evidence` is placed in a designated non-authoritative metadata envelope; it does not touch the `AuthorizationV1` field.

```python
# Step 1 — obtain routing evidence (advisory, may be None)
try:
    ecu = wisepick_client.decide(user_task)
    routing_evidence = AetherisRoutingAdvisor(ecu).to_evidence().model_dump()
except Exception:
    routing_evidence = None  # routing failure does not block the request

# Step 2 — build Aetheris request
#   AuthorizationV1 is assembled from Writ, policy context, and world state.
#   routing_evidence is placed in a separate, clearly-labelled envelope.
request = {
    "authorization": build_authorization_v1(writ, policy_context, world),  # authoritative
    "metadata": {                                                             # non-authoritative
        "routing_evidence": routing_evidence,  # advisory; MUST NOT be read by PEP
    },
}

# Step 3 — submit to Aetheris runtime
#   The policy engine receives only `authorization`; it does not see `metadata`.
result = aetheris_runtime.submit(request)

# Step 4 — record audit correlation (optional)
if routing_evidence and result.decision_id:
    audit_store.record(
        aetheris_decision_id=result.decision_id,
        wisepick_decision_id=routing_evidence["decision_id"],
        decision_hash=compute_decision_hash(routing_evidence),
    )
```

**Invariants that MUST hold:**

- `build_authorization_v1` MUST NOT read `routing_evidence`.
- The policy engine MUST NOT receive `routing_evidence` as part of its `(Intent, Writ, World)` triple.
- PEP tool-scope enforcement MUST derive allowed operations from the Writ only.
- Audit logging MAY read `routing_evidence` after a Permit decision; it confers no authority.

---

## References

| Resource | Path |
| --- | --- |
| Adapter implementation | [`adapters/aetheris_adapter.py`](../../adapters/aetheris_adapter.py) |
| Shared encoding helpers | [`adapters/utils.py`](../../adapters/utils.py) |
| Replay / idempotency semantics | [AGENTS.md — Durable execution replay semantics](../../AGENTS.md#durable-execution-replay-semantics) |
| WisePick responsibility boundary | [docs/ADAPTER_PATTERN.md](../ADAPTER_PATTERN.md) |
| SafeAgent integration (parallel pattern) | [docs/integrations/safeagent.md](./safeagent.md) |
