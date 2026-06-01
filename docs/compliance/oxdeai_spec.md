# OxDeAI External Interoperability — AetherisRouteEvidence

---

> ## NON-AUTHORITATIVE — READ FIRST
>
> **`AetherisRouteEvidence` is audit metadata only.** It MUST NOT be passed into `AuthorizationV1`, PEP enforcement, or any permit/deny decision path.
>
> | Rule | Requirement |
> | --- | --- |
> | Authorization input | **Never** |
> | Missing evidence | MUST NOT change authorization outcomes |
> | Hash match | MUST NOT be treated as a permit signal |
> | Malformed evidence | MUST NOT cause request rejection (audit tooling only) |
>
> **Routing proposes. Authorization decides. PEP enforces.**

---

Schema: [`aetheris_route_evidence.json`](./aetheris_route_evidence.json)

Verifier (locked test vector): [`verify_aetheris_route_evidence_vector.py`](./verify_aetheris_route_evidence_vector.py)

---

## 1. Wire artifact

| Field | Type | In `decision_hash` preimage |
| --- | --- | --- |
| `decision_hash` | `string` (64 hex) | **No** (computed output) |
| `routing_decision_id` | `string` (optional) | **Yes**, as preimage key `decision_id` when present |
| `selected` | normalized `string` | **Yes**, as preimage key `selected_capability` |
| `alternatives` | `string[]` | **Yes**, merged into preimage key `candidate_list` |
| `confidence_bps` | `integer` [0, 10000] | **Yes**, as preimage key `score_bps` |
| `reason_codes` | `string[]` | **Yes**, sorted lexicographically |
| `latency_estimate_ms` | `integer` | **No** (non-identity estimate) |
| `cost_estimate_millicents` | `integer` | **No** (non-identity estimate) |

**Normalization:** all route tokens (`selected`, each `alternatives` entry) MUST be `value.strip().lower()` before serialization (same helpers as `adapters/utils.py`: `normalize_capability_id`, `normalize_provider`).

**Prohibited on wire:** floating-point numbers.

### 1.1 Integer field parity with `thymos_adapter.py`

These wire names and encodings are **shared** with OpenThymos-oriented adapters (basis points, USD millicents):

| Wire field | Encoding | Shared helper |
| --- | --- | --- |
| `confidence_bps` | `0–10000` integer | `confidence_to_basis_points()` |
| `cost_estimate_millicents` | USD millicents (`1 USD = 100_000`) | `usd_to_millicents()` |
| `latency_estimate_ms` | non-negative integer | adapter estimate boundary |

### 1.2 Route label divergence (OxDeAI ≠ OpenThymos)

OxDeAI **`AetherisRouteEvidence`** and OpenThymos **`RoutingEvidence`** (`thymos_adapter.py`) use **different route label semantics**:

| Surface | `selected` example | `alternatives` example |
| --- | --- | --- |
| **OxDeAI (this spec)** | `audio_transcription` (capability_id) | `tongyi_tingwu` (provider token) |
| **OpenThymos (`thymos_adapter`)** | `feishu_minutes:audio_transcription` | `tongyi_tingwu:audio_transcription` |

Do not conflate the two contracts. Integer fields align; route strings do not.

---

## 2. Locked reference vector

The following payload is the **only** approved reference vector for issue #122 / OxDeAI review. Manual reproduction MUST yield the hash below exactly.

```json
{
  "routing_decision_id": "dec_aetheris_demo_001",
  "selected": "audio_transcription",
  "alternatives": ["tongyi_tingwu"],
  "confidence_bps": 7500,
  "reason_codes": ["capability_match"],
  "latency_estimate_ms": 45000,
  "cost_estimate_millicents": 18000
}
```

After attaching `decision_hash`:

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

Source mapping: WisePick ECU with `confidence = 0.75`, `capability_id = audio_transcription`, ranked candidates `feishu_minutes` (primary) and `tongyi_tingwu` (alternate label in `alternatives`).

---

## 3. `decision_hash` canonicalization (LOCKED — `oxdeai_v1`)

### 3.1 Algorithm

Given wire fields **excluding** `decision_hash`, `latency_estimate_ms`, and `cost_estimate_millicents`:

1. Let `selected = evidence["selected"]` (already normalized).
2. Let `alternatives = list(evidence.get("alternatives") or [])`.
3. Build `candidate_list`:
   - Start with `[selected]`.
   - Append each alternative not already present, preserving order.
4. Build preimage object using **legacy-stable internal keys** (not wire keys):

| Preimage key | Source |
| --- | --- |
| `decision_id` | `routing_decision_id` when present; **omit key entirely** when absent |
| `selected_capability` | `selected` |
| `candidate_list` | step 3 |
| `score_bps` | `int(confidence_bps)` |
| `reason_codes` | `sorted(evidence["reason_codes"])` lexicographically |

5. Serialize preimage to **canonical JSON**:
   - UTF-8
   - Object keys sorted lexicographically (`sort_keys=true`)
   - No insignificant whitespace: `separators=(",", ":")`
   - `ensure_ascii=False`
   - No floats anywhere in the tree
6. `decision_hash = SHA-256(utf8_bytes).hexdigest()` (lowercase hex, 64 chars)

### 3.2 Locked canonical preimage string (reference vector)

**Copy exactly — no reformatting, no spaces:**

```text
{"candidate_list":["audio_transcription","tongyi_tingwu"],"decision_id":"dec_aetheris_demo_001","reason_codes":["capability_match"],"score_bps":7500,"selected_capability":"audio_transcription"}
```

**Locked SHA-256 output:**

```text
306b3c59d4eb15efac1f31cb3dda6454538e442f423a366d950b7008946debaa
```

### 3.3 Manual reproduction (any language)

1. Start from the wire object in §2 **without** `decision_hash`.
2. Build the preimage object per §3.1 step 4.
3. JSON-encode with sorted keys and `,` / `:` separators only.
4. UTF-8-encode the string and SHA-256 the bytes.
5. Compare to `306b3c59…` — mismatch means canonicalization drift; fix before merging.

Python (matches verifier):

```python
import hashlib, json

evidence = {
    "routing_decision_id": "dec_aetheris_demo_001",
    "selected": "audio_transcription",
    "alternatives": ["tongyi_tingwu"],
    "confidence_bps": 7500,
    "reason_codes": ["capability_match"],
    "latency_estimate_ms": 45000,
    "cost_estimate_millicents": 18000,
}

selected = evidence["selected"]
alternatives = list(evidence["alternatives"])
candidate_list = [selected]
for label in alternatives:
    if label not in candidate_list:
        candidate_list.append(label)

preimage = {
    "selected_capability": selected,
    "candidate_list": candidate_list,
    "score_bps": int(evidence["confidence_bps"]),
    "reason_codes": sorted(evidence["reason_codes"]),
}
if evidence.get("routing_decision_id"):
    preimage["decision_id"] = str(evidence["routing_decision_id"])

canonical = json.dumps(preimage, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
assert canonical == (
    '{"candidate_list":["audio_transcription","tongyi_tingwu"],'
    '"decision_id":"dec_aetheris_demo_001",'
    '"reason_codes":["capability_match"],'
    '"score_bps":7500,'
    '"selected_capability":"audio_transcription"}'
)
print(hashlib.sha256(canonical.encode("utf-8")).hexdigest())
# 306b3c59d4eb15efac1f31cb3dda6454538e442f423a366d950b7008946debaa
```

### 3.4 Reference verifier (CI / local)

```bash
python docs/compliance/verify_aetheris_route_evidence_vector.py
```

The script asserts the canonical preimage string, full wire payload, zero floats, and the locked hash.

---

## 4. Non-authoritative declaration (normative)

> **Repeat:** `decision_hash` and the entire `AetherisRouteEvidence` artifact are **audit metadata only**.

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

## 6. Relationship to WisePick adapters

| Component | Role |
| --- | --- |
| [`adapters/aetheris_adapter.py`](../../adapters/aetheris_adapter.py) | Maps WisePick ECU → internal evidence (`score_bps`, `candidate_list`, …) |
| [`adapters/thymos_adapter.py`](../../adapters/thymos_adapter.py) | OpenThymos `RoutingEvidence` (`provider:capability` labels; different `decision_hash` preimage) |
| OxDeAI wire schema | Compliance-facing envelope consumed by audit stores |
| [`adapters/utils.py`](../../adapters/utils.py) | Shared integer encoding and normalization |

OxDeAI consumers map adapter output to this wire schema before attaching to request metadata.

---

## References

- Integration overview: [`docs/integrations/aetheris.md`](../integrations/aetheris.md)
- Agent replay semantics: [`AGENTS.md`](../../AGENTS.md#durable-execution-replay-semantics)
- Replay fixture: [`tests/fixtures/aetheris_replay/deterministic_suite_v1.json`](../../tests/fixtures/aetheris_replay/deterministic_suite_v1.json)
