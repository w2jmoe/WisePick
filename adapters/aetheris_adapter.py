"""
Aetheris runtime adapter — maps WisePick DecideResponse → narrow audit evidence.

Does not call WisePick HTTP or modify core API code.
"""

from __future__ import annotations

from typing import Any, Union

from pydantic import BaseModel, Field

from app.schemas.decide import DecideResponse

_LOW_CONFIDENCE_THRESHOLD = 0.01
_FALLBACK_CAPABILITY_IDS = frozenset({"none", "general_capability", ""})


class AetherisRouteEvidence(BaseModel):
    """First-class audit bundle expected by Aetheris evidence store."""

    decision_id: str
    candidate_list: list[str] = Field(
        default_factory=list,
        description="Ranked capability/provider labels (from trace.top_candidates, max 5 today).",
    )
    score: float = Field(..., description="Routing score; sourced from WisePick confidence.")
    reason_codes: list[str] = Field(
        default_factory=list,
        description='Structured routing rationale, e.g. ["capability_match"] or ["fallback_routing"].',
    )
    selected_capability: str = Field(
        ...,
        description="Winning capability_id from the ECU.",
    )


def _coerce_decide_response(decision: Union[DecideResponse, dict[str, Any]]) -> DecideResponse:
    if isinstance(decision, DecideResponse):
        return decision
    if isinstance(decision, dict):
        return DecideResponse(**decision)
    raise TypeError("decision must be DecideResponse or dict")


def _extract_candidate_list(response: DecideResponse) -> list[str]:
    """Safe extraction from trace.top_candidates; never raises."""
    trace = response.trace if isinstance(response.trace, dict) else {}
    raw = trace.get("top_candidates")
    if not isinstance(raw, list):
        raw = []

    ordered: list[str] = []
    seen: set[str] = set()

    for item in raw:
        if not isinstance(item, dict):
            continue
        capability_id = str(item.get("capability_id") or "").strip()
        provider = str(item.get("provider") or item.get("tool_key") or "").strip()
        cap_ok = capability_id and capability_id not in _FALLBACK_CAPABILITY_IDS
        if cap_ok and capability_id not in seen:
            label = capability_id
        elif provider and provider not in seen:
            label = provider
        else:
            continue
        seen.add(label)
        ordered.append(label)

    if not ordered:
        selected = (response.capability_id or response.provider or "").strip()
        if selected and selected not in _FALLBACK_CAPABILITY_IDS:
            ordered.append(selected)

    return ordered


def _build_reason_codes(response: DecideResponse) -> list[str]:
    """
    Lightweight reason codes for Aetheris (aligned with langfuse_emitter semantics).

    Returns capability_match when bootstrap/capability signals exist; else fallback_routing.
    """
    if not response.callable:
        return ["fallback_routing"]

    confidence = float(response.confidence)
    if confidence < _LOW_CONFIDENCE_THRESHOLD:
        return ["fallback_routing"]

    explain = response.explain if isinstance(response.explain, dict) else {}
    selected = explain.get("selected_capability")
    if isinstance(selected, dict):
        matched = selected.get("matched_capabilities") or []
        if matched:
            return ["capability_match"]

    cap = (response.capability_id or "").strip()
    if cap and cap not in _FALLBACK_CAPABILITY_IDS:
        return ["capability_match"]

    return ["fallback_routing"]


class AetherisRoutingAdvisor:
    """Translates a WisePick ECU/decide payload into AetherisRouteEvidence."""

    def __init__(self, decision: Union[DecideResponse, dict[str, Any]]) -> None:
        self._decision = _coerce_decide_response(decision)

    def to_evidence(self) -> AetherisRouteEvidence:
        d = self._decision
        selected = (d.capability_id or "").strip() or (d.provider or "").strip()

        return AetherisRouteEvidence(
            decision_id=d.decision_id,
            candidate_list=_extract_candidate_list(d),
            score=float(d.confidence),
            reason_codes=_build_reason_codes(d),
            selected_capability=selected,
        )


def test_adapter_mapping() -> dict[str, Any]:
    """
    Mock decide payload → Aetheris evidence JSON-shaped dict.

    Run: python -m adapters.aetheris_adapter
    """
    mock_decide: dict[str, Any] = {
        "decision_id": "dec_aetheris_demo_001",
        "capability_id": "audio_transcription",
        "execution_type": "api",
        "provider": "feishu_minutes",
        "callable": True,
        "tool_key": "feishu_minutes",
        "reason": "Capability routing matched: audio_transcription; Confidence score: 0.75",
        "confidence": 0.75,
        "explain": {
            "candidate_count": 4,
            "selected_capability": {
                "capability_id": "audio_transcription",
                "provider": "feishu_minutes",
                "score": 0.75,
                "matched_capabilities": ["audio_transcription"],
            },
        },
        "trace": {
            "latency_ms": 3,
            "top_candidates": [
                {
                    "capability_id": "audio_transcription",
                    "provider": "feishu_minutes",
                    "score": 0.75,
                    "rank": 1,
                },
                {
                    "capability_id": "audio_transcription",
                    "provider": "tongyi_tingwu",
                    "score": 0.7,
                    "rank": 2,
                },
            ],
        },
    }

    evidence = AetherisRoutingAdvisor(mock_decide).to_evidence()
    payload = evidence.model_dump()

    assert payload["decision_id"] == "dec_aetheris_demo_001"
    assert payload["score"] == 0.75
    assert payload["selected_capability"] == "audio_transcription"
    assert payload["reason_codes"] == ["capability_match"]
    assert payload["candidate_list"] == ["audio_transcription", "tongyi_tingwu"]

    fallback = AetherisRoutingAdvisor(
        {
            **mock_decide,
            "confidence": 0.0,
            "callable": False,
            "explain": {},
            "trace": {},
        }
    ).to_evidence()
    assert fallback.reason_codes == ["fallback_routing"]

    return payload


if __name__ == "__main__":
    import json

    result = test_adapter_mapping()
    print(json.dumps(result, indent=2, ensure_ascii=False))
