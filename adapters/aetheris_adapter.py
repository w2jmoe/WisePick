"""
Aetheris runtime adapter — maps WisePick DecideResponse → narrow audit evidence.

Does not call WisePick HTTP or modify core API code.
"""

from __future__ import annotations

from typing import Any, Union

from pydantic import BaseModel, Field

from adapters.utils import (
    build_reason_codes_from_decide,
    confidence_to_basis_points,
    normalize_capability_id,
    normalize_provider,
    normalize_route_token,
)
from app.schemas.decide import DecideResponse

_FALLBACK_CAPABILITY_IDS = frozenset({"none", "general_capability", ""})


class AetherisRouteEvidence(BaseModel):
    """First-class audit bundle expected by Aetheris evidence store."""

    decision_id: str
    candidate_list: list[str] = Field(
        default_factory=list,
        description="Ranked capability/provider labels (from trace.top_candidates, max 5 today).",
    )
    score_bps: int = Field(
        ...,
        ge=0,
        le=10_000,
        description="Routing score in basis points; sourced from WisePick confidence.",
    )
    reason_codes: list[str] = Field(
        default_factory=list,
        description='Structured routing rationale, e.g. ["capability_match"] or ["fallback_routing"].',
    )
    selected_capability: str = Field(
        ...,
        description="Winning capability_id from the ECU (normalized).",
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
        capability_id = normalize_capability_id(str(item.get("capability_id") or ""))
        provider = normalize_provider(str(item.get("provider") or item.get("tool_key") or ""))
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
        selected = normalize_route_token(response.capability_id or response.provider or "")
        if selected and selected not in _FALLBACK_CAPABILITY_IDS:
            ordered.append(selected)

    return ordered


class AetherisRoutingAdvisor:
    """Translates a WisePick ECU/decide payload into AetherisRouteEvidence."""

    def __init__(self, decision: Union[DecideResponse, dict[str, Any]]) -> None:
        self._decision = _coerce_decide_response(decision)

    def to_evidence(self) -> AetherisRouteEvidence:
        d = self._decision
        selected = normalize_capability_id(d.capability_id or "") or normalize_provider(
            d.provider or ""
        )
        explain = d.explain if isinstance(d.explain, dict) else {}

        return AetherisRouteEvidence(
            decision_id=d.decision_id,
            candidate_list=_extract_candidate_list(d),
            score_bps=confidence_to_basis_points(d.confidence),
            reason_codes=build_reason_codes_from_decide(
                callable=d.callable,
                confidence=d.confidence,
                capability_id=d.capability_id,
                explain=explain,
            ),
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
    assert payload["score_bps"] == 7500
    assert payload["selected_capability"] == "audio_transcription"
    assert payload["reason_codes"] == ["capability_match"]
    assert payload["candidate_list"] == ["audio_transcription", "tongyi_tingwu"]

    fallback = AetherisRoutingAdvisor(
        {
            **mock_decide,
            "confidence": 0,
            "callable": False,
            "explain": {},
            "trace": {},
        }
    ).to_evidence()
    assert fallback.reason_codes == ["fallback_routing"]
    assert fallback.score_bps == 0

    return payload


if __name__ == "__main__":
    import json

    result = test_adapter_mapping()
    print(json.dumps(result, indent=2, ensure_ascii=False))
