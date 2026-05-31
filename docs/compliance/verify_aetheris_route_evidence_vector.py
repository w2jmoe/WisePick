#!/usr/bin/env python3
"""
OxDeAI AetherisRouteEvidence reference vector verifier.

Run from repo root:
  python docs/compliance/verify_aetheris_route_evidence_vector.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REFERENCE_DECISION_HASH = (
    "306b3c59d4eb15efac1f31cb3dda6454538e442f423a366d950b7008946debaa"
)

REFERENCE_VECTOR: dict[str, Any] = {
    "routing_decision_id": "dec_aetheris_demo_001",
    "selected": "audio_transcription",
    "alternatives": ["tongyi_tingwu"],
    "confidence_bps": 7500,
    "reason_codes": ["capability_match"],
    "latency_estimate_ms": 45000,
    "cost_estimate_millicents": 18000,
}


def build_candidate_list(selected: str, alternatives: list[str]) -> list[str]:
    ordered = [selected]
    for label in alternatives:
        if label not in ordered:
            ordered.append(label)
    return ordered


def canonical_preimage(evidence: dict[str, Any]) -> dict[str, Any]:
    """
    OxDeAI decision_hash preimage (audit identity only).

    - Uses legacy-stable internal keys for cross-release replay compatibility.
    - Excludes decision_hash, latency_estimate_ms, cost_estimate_millicents.
    - Includes routing_decision_id as decision_id when present.
    """
    selected = evidence["selected"]
    alternatives = list(evidence.get("alternatives") or [])
    preimage: dict[str, Any] = {
        "selected_capability": selected,
        "candidate_list": build_candidate_list(selected, alternatives),
        "score_bps": int(evidence["confidence_bps"]),
        "reason_codes": sorted(evidence["reason_codes"]),
    }
    routing_decision_id = evidence.get("routing_decision_id")
    if routing_decision_id:
        preimage["decision_id"] = str(routing_decision_id)
    return preimage


def canonical_json_bytes(preimage: dict[str, Any]) -> bytes:
    return json.dumps(
        preimage,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def compute_decision_hash(evidence: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(canonical_preimage(evidence))).hexdigest()


def attach_decision_hash(evidence: dict[str, Any]) -> dict[str, Any]:
    out = dict(evidence)
    out["decision_hash"] = compute_decision_hash(out)
    return out


def assert_no_floats(obj: Any) -> None:
    if isinstance(obj, float):
        raise TypeError("float values are prohibited on the OxDeAI wire surface")
    if isinstance(obj, dict):
        for value in obj.values():
            assert_no_floats(value)
    elif isinstance(obj, list):
        for item in obj:
            assert_no_floats(item)


def main() -> None:
    vector = attach_decision_hash(REFERENCE_VECTOR)
    preimage = canonical_preimage(REFERENCE_VECTOR)
    canonical = canonical_json_bytes(preimage).decode("utf-8")

    assert vector["decision_hash"] == REFERENCE_DECISION_HASH, (
        f"expected {REFERENCE_DECISION_HASH}, got {vector['decision_hash']}"
    )
    assert_no_floats(vector)

    print("OxDeAI AetherisRouteEvidence reference vector: PASS")
    print()
    print("Canonical preimage JSON:")
    print(canonical)
    print()
    print("decision_hash:")
    print(vector["decision_hash"])
    print()
    print("Full wire payload:")
    print(json.dumps(vector, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
