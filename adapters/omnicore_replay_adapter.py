"""
OmniCore replay adapter — maps WisePick DecideResponse → deterministic replay evidence.

Mirrors the SafeAgent / Aetheris narrow-contract pattern: integer wire encoding,
normalized route tokens, no floats in replay payloads.

Does not call WisePick HTTP or modify core API code.
"""

from __future__ import annotations

from typing import Any, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from adapters.utils import (
    FALLBACK_CAPABILITY_IDS,
    assert_no_floats,
    build_reason_codes_from_decide,
    confidence_to_basis_points,
    normalize_capability_id,
    normalize_provider,
    normalize_route_token,
)
from app.schemas.decide import DecideResponse


class OmniCoreReplayEvidence(BaseModel):
    """Immutable runtime evidence for OmniCore deterministic replay."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str
    candidate_list: list[str] = Field(
        default_factory=list,
        description="Ranked capability/provider labels (normalized, max 5 from trace today).",
    )
    confidence_bps: int = Field(
        ...,
        ge=0,
        le=10_000,
        description="Routing confidence in basis points; sourced from WisePick confidence.",
    )
    reason_codes: list[str] = Field(
        default_factory=list,
        description='Structured routing rationale, e.g. ["capability_match"] or ["fallback_routing"].',
    )
    selected_capability: str = Field(
        ...,
        description="Winning capability_id (normalized strip + lower).",
    )

    @field_validator("selected_capability")
    @classmethod
    def _normalize_selected(cls, value: str) -> str:
        return normalize_route_token(value)

    @field_validator("candidate_list")
    @classmethod
    def _normalize_candidates(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for item in value:
            token = normalize_route_token(str(item))
            if not token or token in seen:
                continue
            seen.add(token)
            out.append(token)
        return out


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
        cap_ok = capability_id and capability_id not in FALLBACK_CAPABILITY_IDS
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
        if selected and selected not in FALLBACK_CAPABILITY_IDS:
            ordered.append(selected)

    return ordered


class OmniCoreRoutingAdvisor:
    """Translates a WisePick ECU/decide payload into OmniCoreReplayEvidence."""

    def __init__(self, decision: Union[DecideResponse, dict[str, Any]]) -> None:
        self._decision = _coerce_decide_response(decision)

    def to_evidence(self) -> OmniCoreReplayEvidence:
        d = self._decision
        explain = d.explain if isinstance(d.explain, dict) else {}
        selected = normalize_capability_id(d.capability_id or "") or normalize_provider(
            d.provider or ""
        )

        return OmniCoreReplayEvidence(
            decision_id=d.decision_id,
            candidate_list=_extract_candidate_list(d),
            confidence_bps=confidence_to_basis_points(d.confidence),
            reason_codes=build_reason_codes_from_decide(
                callable=d.callable,
                confidence=d.confidence,
                capability_id=d.capability_id,
                explain=explain,
            ),
            selected_capability=selected,
        )


def _self_test() -> dict[str, Any]:
    """Simulated ECU → replay evidence; integer-only wire + normalized tokens."""
    mock_ecu: dict[str, Any] = {
        "decision_id": "dec_omnicore_replay_001",
        "capability_id": " JSON_Document_Migration ",
        "execution_type": "api",
        "provider": " CouchDB_Replicator ",
        "callable": True,
        "tool_key": "couchdb_replicator",
        "reason": "Capability routing matched: json_document_migration",
        "confidence": 0.91,
        "explain": {
            "candidate_count": 3,
            "selected_capability": {
                "capability_id": "json_document_migration",
                "provider": "couchdb_replicator",
                "score": 0.91,
                "matched_capabilities": ["json_document_migration"],
            },
        },
        "trace": {
            "latency_ms": 2,
            "top_candidates": [
                {
                    "capability_id": " JSON_Document_Migration ",
                    "provider": " CouchDB_Replicator ",
                    "score": 0.91,
                    "rank": 1,
                },
                {
                    "capability_id": "json_document_migration",
                    "provider": " Postgres_Bulk_Loader ",
                    "score": 0.72,
                    "rank": 2,
                },
            ],
        },
    }

    evidence = OmniCoreRoutingAdvisor(mock_ecu).to_evidence()
    payload = evidence.model_dump()

    assert payload["decision_id"] == "dec_omnicore_replay_001"
    assert payload["confidence_bps"] == 9100
    assert isinstance(payload["confidence_bps"], int)
    assert payload["selected_capability"] == "json_document_migration"
    assert payload["candidate_list"] == [
        "json_document_migration",
        "postgres_bulk_loader",
    ]
    assert payload["reason_codes"] == ["capability_match"]
    assert_no_floats(payload)

    fallback = OmniCoreRoutingAdvisor(
        {
            **mock_ecu,
            "confidence": 0.0,
            "callable": False,
            "explain": {},
            "trace": {},
        }
    ).to_evidence()
    assert fallback.confidence_bps == 0
    assert fallback.reason_codes == ["fallback_routing"]
    assert_no_floats(fallback.model_dump())

    return payload


if __name__ == "__main__":
    import json

    result = _self_test()
    print(json.dumps(result, indent=2, ensure_ascii=False))
