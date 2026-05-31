# OxDeAI External Interoperability — AetherisRouteEvidence

> **Principle:** Routing proposes. Authorization decides. PEP enforces.
>
> WisePick is not on the authorization path. `AetherisRouteEvidence` is audit-only metadata.

Schema: [`aetheris_route_evidence.json`](./aetheris_route_evidence.json)

Verifier: [`verify_aetheris_route_evidence_vector.py`](./verify_aetheris_route_evidence_vector.py)

---

## 1. Wire artifact

| Field | Type | In `decision_hash` preimage |
| --- | --- | --- |
| `decision_hash` | `string` (64 hex) | **No** (computed output) |
| `routing_decision_id` | `string` (optional) | **Yes**, as `decision_id` when present |
| `selected` | normalized `string` | **Yes**, as `selected_capability` |
| `alternatives` | `string[]` | **Yes**, merged into `candidate_list` |
| `confidence_bps` | `integer` [0, 10000] | **Yes**, as `score_bps` |
| `reason_codes` | `string[]` | **Yes**, sorted lexicographically |
| `latency_estimate_ms` | `integer` | **No** (non-identity estimate) |
| `cost_estimate_millicents` | `integer` | **No** (non-identity estimate) |

**Normalization:** all route tokens (`selected`, each `alternatives` entry) MUST be `value.strip().lower()` before serialization.

**Prohibited on wire:** floating-point numbers.

---

## 2. Complete example payload

Verified reference vector (produces `decision_hash = 306b3c59…`):

```json
{
  "decision_hash": "306b3c59d4eb15efac1f31cb3dda6454538e442f423a366d950b7008946debaa",
  "routing_decision_id": "dec_aetheris_demo_001",
  "selected": "audio_transcription",
  "alternatives": ["tongyi_tingwu"],
  "confidence_bps": 7500,
  "reason_codes": ["capability_match"],
  "latency_estimate_ms": 45000,
  "cost_estimate_millicents": 18000
}
```

Source mapping: WisePick ECU with `confidence = 0.75`, `capability_id = audio_transcription`, ranked candidates `feishu_minutes` (primary) and `tongyi_tingwu` (alternate label).

---

## 3. `decision_hash` canonicalization

### 3.1 Steps

1. Normalize `selected` and every `alternatives` entry: `.strip().lower()`.
2. Build `candidate_list`:
   - Start with `[selected]`.
   - Append each alternative not already present, preserving order.
3. Build preimage object (legacy-stable internal keys):

```json
{
  "decision_id": "<routing_decision_id when present>",
  "selected_capability": "<selected>",
  "candidate_list": ["<selected>", "..."],
  "score_bps": <confidence_bps>,
  "reason_codes": ["<sorted>"]
}
```

4. Omit `decision_id` key entirely when `routing_decision_id` is absent.
5. Serialize preimage to **canonical JSON**:
   - UTF-8
   - Object keys sorted lexicographically (`sort_keys=true`)
   - No insignificant whitespace (`separators=(",", ":")`)
   - No floats
6. `decision_hash = SHA-256(canonical_json_bytes).hexdigest()`

### 3.2 Verified canonical preimage (reference vector)

```text
{"candidate_list":["audio_transcription","tongyi_tingwu"],"decision_id":"dec_aetheris_demo_001","reason_codes":["capability_match"],"score_bps":7500,"selected_capability":"audio_transcription"}
```

```text
SHA-256 = 306b3c59d4eb15efac1f31cb3dda6454538e442f423a366d950b7008946debaa
```

### 3.3 Reference verifier

```bash
python docs/compliance/verify_aetheris_route_evidence_vector.py
```

The script prints the canonical preimage, full wire payload, and asserts the reference hash.

---

## 4. Non-authoritative declaration

`decision_hash` and the entire `AetherisRouteEvidence` artifact are **audit metadata only**.

| Property | Value |
| --- | --- |
| Authorization input | **Never** |
| `AuthorizationV1` verification | **Not read, not validated, not required** |
| PEP enforcement | **No effect** |
| Trust model | Untrusted producer metadata; advisory routing context |
| Absence semantics | Missing evidence MUST NOT change authorization outcomes |

Implementations MUST NOT:

- Pass `decision_hash` or any evidence field into `AuthorizationV1` construction.
- Treat a matching `decision_hash` as a permit signal.
- Reject a request because evidence is missing, malformed, or hash-mismatched (hash checks belong in audit/replay tooling only).

---

## 5. Envelope attachment (non-authoritative)

### Python

```python
evidence = attach_decision_hash({
    "routing_decision_id": ecu["decision_id"],
    "selected": normalize_capability_id(ecu["capability_id"]),
    "alternatives": extract_alternatives(ecu),
    "confidence_bps": confidence_to_basis_points(ecu["confidence"]),
    "reason_codes": build_reason_codes_from_decide(...),
    "latency_estimate_ms": 45000,
    "cost_estimate_millicents": 18000,
})

request = {
    "authorization": build_authorization_v1(writ, policy_ctx, world),  # authoritative
    "metadata": {
        "routing_evidence": evidence,  # non-authoritative; PEP MUST ignore
    },
}
# Policy engine input: request["authorization"] only
```

### Go (illustrative)

```go
type Request struct {
    Authorization AuthorizationV1 `json:"authorization"`
    Metadata      struct {
        RoutingEvidence map[string]any `json:"routing_evidence,omitempty"`
    } `json:"metadata"`
}

func Submit(req Request) error {
    // PEP and policy MUST use req.Authorization only.
    _ = req.Metadata.RoutingEvidence // audit / observability only
    return policyEngine.Evaluate(req.Authorization)
}
```

### Rust (illustrative)

```rust
struct Request {
    authorization: AuthorizationV1,
    metadata: Option<Metadata>,
}

struct Metadata {
    routing_evidence: Option<serde_json::Value>,
}

// routing_evidence is never passed to authorize() or pep.enforce().
```

---

## 6. Relationship to WisePick adapter

| Component | Role |
| --- | --- |
| [`adapters/aetheris_adapter.py`](../../adapters/aetheris_adapter.py) | Maps WisePick ECU → internal evidence (`score_bps`, `candidate_list`, …) |
| OxDeAI wire schema | Compliance-facing envelope consumed by audit stores |
| [`adapters/utils.py`](../../adapters/utils.py) | Shared normalization and basis-point encoding |

OxDeAI consumers map adapter output to this wire schema before attaching to request metadata.

---

## References

- Integration overview: [`docs/integrations/aetheris.md`](../integrations/aetheris.md)
- Agent replay semantics: [`AGENTS.md`](../../AGENTS.md#durable-execution-replay-semantics)
