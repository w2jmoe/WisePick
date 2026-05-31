"""
WisePick → THYMOS adapter (Proposal Contract v1, Option 2).

Maps WisePick ECU / routing outcomes to THYMOS ``RoutingEvidence`` and attaches it
at the **Proposal** envelope — never inside ``ProposalBody`` — so
``ProposalId = blake3(canonical_json(ProposalBody))`` is unchanged.

RFC: OpenThymos ``docs/rfcs/proposal-contract-v1.md`` (Accepted); provider routing
metadata via ``routing_evidence`` on ``Proposal``, outside the content-addressed body.

Does not call THYMOS HTTP or the WisePick API.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Mapping, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.decide import DecideResponse

_LOW_CONFIDENCE_THRESHOLD = 0.01
_FALLBACK_CAPABILITY_IDS = frozenset({"none", "general_capability", ""})
_ROUTE_LABEL_SEP = "/"
_BASIS_POINTS_SCALE = 10_000
_USD_MILLICENTS_SCALE = 100_000  # 1 USD = 100_000 millicents (1 millicent = $0.00001)


# ── THYMOS wire types (integer-only numerics for replay determinism) ─────────


class FallbackHint(BaseModel):
    """THYMOS fallback topology hint; carried in ``RoutingEvidence`` only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1, description="Capability / route model id (not an LLM name).")
    reason: str = Field(..., min_length=1)


class RoutingEvidence(BaseModel):
    """
    Provider routing metadata for THYMOS proposal stage (outside ``ProposalBody``).

    All numeric fields are integers — no floats on the replay/canonical surface.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_hash: str = Field(..., min_length=64, max_length=64)
    selected: str = Field(..., min_length=1)
    alternatives: list[str] = Field(default_factory=list)
    confidence: int = Field(..., ge=0, le=_BASIS_POINTS_SCALE)
    reason_codes: list[str] = Field(..., min_length=1)
    latency_estimate_ms: int = Field(..., ge=0)
    cost_estimate_usd: int = Field(..., ge=0, description="USD millicents (1 USD = 100_000).")
    fallback_hint: FallbackHint

    @model_validator(mode="after")
    def _selected_not_in_alternatives(self) -> RoutingEvidence:
        if self.selected in self.alternatives:
            raise ValueError("alternatives must not include selected route label")
        return self


# ── Encoding helpers ───────────────────────────────────────────────────────────


def format_route_label(capability_id: str, provider: str) -> str:
    """Canonical route label: ``{capability_id}/{provider}``."""
    cap = (capability_id or "").strip()
    prov = (provider or "").strip()
    if not cap or not prov:
        raise ValueError("capability_id and provider are required for route label")
    return f"{cap}{_ROUTE_LABEL_SEP}{prov}"


def confidence_to_basis_points(confidence: float) -> int:
    """Map WisePick score in [0, 1] (or already basis points) to 0–10000."""
    value = float(confidence)
    if value > 1.0:
        if value <= _BASIS_POINTS_SCALE:
            return int(round(value))
        return _BASIS_POINTS_SCALE
    return min(_BASIS_POINTS_SCALE, max(0, int(round(value * _BASIS_POINTS_SCALE))))


def usd_to_millicents(amount_usd: float) -> int:
    """Convert USD float estimate to integer millicents (replay-safe)."""
    return max(0, int(round(float(amount_usd) * _USD_MILLICENTS_SCALE)))


def compute_routing_decision_hash(
    *,
    selected: str,
    alternatives: list[str],
    reason_codes: list[str],
    confidence: int,
    latency_estimate_ms: int,
    cost_estimate_usd: int,
    fallback_hint: FallbackHint,
) -> str:
    """
    Replay-stable SHA-256 over integer-only routing fields.

    Excludes ephemeral WisePick ``decision_id`` and any float-derived wire values.
    """
    preimage_obj: dict[str, Any] = {
        "selected": selected,
        "alternatives": list(alternatives),
        "reason_codes": sorted(reason_codes),
        "confidence": int(confidence),
        "latency_estimate_ms": int(latency_estimate_ms),
        "cost_estimate_usd": int(cost_estimate_usd),
        "fallback_hint": fallback_hint.model_dump(),
    }
    preimage = json.dumps(
        preimage_obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(preimage.encode("utf-8")).hexdigest()


# ── WisePick ECU → RoutingEvidence ─────────────────────────────────────────────


def _coerce_decide_response(decision: Union[DecideResponse, dict[str, Any]]) -> DecideResponse:
    if isinstance(decision, DecideResponse):
        return decision
    if isinstance(decision, dict):
        return DecideResponse(**decision)
    raise TypeError("decision must be DecideResponse or dict")


def _build_reason_codes(response: DecideResponse) -> list[str]:
    if not response.callable:
        return ["fallback_routing"]
    if float(response.confidence) < _LOW_CONFIDENCE_THRESHOLD:
        return ["fallback_routing"]
    explain = response.explain if isinstance(response.explain, dict) else {}
    selected = explain.get("selected_capability")
    if isinstance(selected, dict) and selected.get("matched_capabilities"):
        return ["capability_match"]
    cap = (response.capability_id or "").strip()
    if cap and cap not in _FALLBACK_CAPABILITY_IDS:
        return ["capability_match"]
    return ["fallback_routing"]


def _ranked_pairs_from_ecu(ecu: Mapping[str, Any]) -> list[tuple[str, str, int]]:
    """Return [(capability_id, provider, rank), ...] sorted by rank."""
    trace = ecu.get("trace") if isinstance(ecu.get("trace"), dict) else {}
    raw = trace.get("top_candidates")
    rows: list[tuple[str, str, int]] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            cap = str(item.get("capability_id") or "").strip()
            prov = str(item.get("provider") or item.get("tool_key") or "").strip()
            if not cap or not prov:
                continue
            rows.append((cap, prov, int(item.get("rank") or len(rows) + 1)))
    if not rows:
        cap = str(ecu.get("capability_id") or "").strip()
        prov = str(ecu.get("provider") or ecu.get("tool_key") or "").strip()
        if cap and prov:
            rows.append((cap, prov, 1))
    rows.sort(key=lambda r: r[2])
    return rows


def _estimate_cost_latency(
    capability_id: str,
    provider: str,
    *,
    constraints: Mapping[str, Any] | None,
) -> tuple[int, int]:
    """Return (latency_estimate_ms, cost_estimate_usd_millicents)."""
    base_latency = {
        "audio_transcription": 45_000,
        "general_content": 8_000,
    }.get(capability_id, 15_000)
    base_cost_usd = {
        ("audio_transcription", "feishu_minutes"): 0.18,
        ("audio_transcription", "tongyi_tingwu"): 0.22,
        ("audio_transcription", "openai"): 0.35,
    }.get((capability_id, provider), 0.12)
    budget_ms = constraints.get("latency_budget_ms") if constraints else None
    if isinstance(budget_ms, (int, float)) and budget_ms > 0:
        base_latency = min(int(base_latency), int(budget_ms))
    ceiling = constraints.get("max_cost_usd") if constraints else None
    if isinstance(ceiling, (int, float)) and ceiling > 0:
        base_cost_usd = min(float(base_cost_usd), float(ceiling))
    return int(base_latency), usd_to_millicents(base_cost_usd)


class ThymosRoutingAdvisor:
    """Translates a WisePick ECU/decide payload into THYMOS ``RoutingEvidence``."""

    def __init__(
        self,
        decision: Union[DecideResponse, dict[str, Any]],
        *,
        constraints: Mapping[str, Any] | None = None,
        fallback_reason: str = "use_alternative_on_primary_failure",
    ) -> None:
        self._decision = _coerce_decide_response(decision)
        self._constraints = dict(constraints or {})
        self._fallback_reason = (fallback_reason or "").strip() or "use_alternative_on_primary_failure"

    def to_evidence(self) -> RoutingEvidence:
        ecu = self._decision.model_dump()
        ranked = _ranked_pairs_from_ecu(ecu)
        if not ranked:
            raise ValueError("ECU must expose at least one ranked capability/provider pair")

        cap0, prov0, _ = ranked[0]
        selected_label = format_route_label(cap0, prov0)
        alt_labels = [format_route_label(c, p) for c, p, _ in ranked[1:3]]

        reason_codes = _build_reason_codes(self._decision)
        confidence = confidence_to_basis_points(float(self._decision.confidence))
        latency_ms, cost_mc = _estimate_cost_latency(cap0, prov0, constraints=self._constraints)

        if len(ranked) > 1:
            cap_alt, prov_alt, _ = ranked[1]
            hint = FallbackHint(
                provider=prov_alt,
                model=cap_alt,
                reason=self._fallback_reason,
            )
        else:
            hint = FallbackHint(
                provider=prov0,
                model=cap0,
                reason="no_alternative_ranked",
            )

        decision_hash = compute_routing_decision_hash(
            selected=selected_label,
            alternatives=alt_labels,
            reason_codes=reason_codes,
            confidence=confidence,
            latency_estimate_ms=latency_ms,
            cost_estimate_usd=cost_mc,
            fallback_hint=hint,
        )

        return RoutingEvidence(
            decision_hash=decision_hash,
            selected=selected_label,
            alternatives=alt_labels,
            confidence=confidence,
            reason_codes=reason_codes,
            latency_estimate_ms=latency_ms,
            cost_estimate_usd=cost_mc,
            fallback_hint=hint,
        )


# ── Proposal attach (Option 2) ─────────────────────────────────────────────────


def _looks_like_proposal_body(payload: Mapping[str, Any]) -> bool:
    return any(
        key in payload
        for key in ("intent_id", "writ_id", "plan", "policy_trace", "status")
    )


def _normalize_proposal_envelope(proposal_body: Mapping[str, Any]) -> dict[str, Any]:
    """
    Normalize input to a Proposal envelope ``{id?, body}``.

    Accepts a full Proposal dict or a bare ProposalBody dict.
    """
    if not isinstance(proposal_body, Mapping):
        raise TypeError("proposal_body must be a mapping")
    data = copy.deepcopy(dict(proposal_body))
    if "body" in data and isinstance(data.get("body"), dict):
        return data
    if _looks_like_proposal_body(data):
        return {"body": data}
    raise ValueError(
        "proposal_body must be a Proposal envelope with 'body' or a ProposalBody-shaped dict"
    )


def attach_routing_evidence_to_proposal(
    proposal_body: dict[str, Any],
    evidence: RoutingEvidence,
) -> dict[str, Any]:
    """
    Attach ``routing_evidence`` at the Proposal layer (RFC Option 2).

    Parameters
    ----------
    proposal_body:
        Proposal envelope ``{"id": ..., "body": {...}}`` or a bare ProposalBody dict
        (wrapped as ``{"body": ...}``). The body is copied verbatim; ``routing_evidence``
        is never nested inside ``body`` so ``ProposalId`` hashing is unaffected.

    Returns
    -------
    dict
        Proposal envelope with top-level ``routing_evidence`` (integer-only fields).
    """
    envelope = _normalize_proposal_envelope(proposal_body)
    body = envelope["body"]

    if "routing_evidence" in body:
        raise ValueError(
            "routing_evidence must not appear inside ProposalBody; "
            "it would change ProposalId = blake3(canonical_json(ProposalBody))"
        )

    wire = evidence.model_dump(mode="json")
    _assert_no_floats(wire)

    out = {**envelope, "routing_evidence": wire}
    if "routing_evidence" in out.get("body", {}):
        raise RuntimeError("internal error: routing_evidence leaked into ProposalBody")
    return out


def _assert_no_floats(obj: Any) -> None:
    if isinstance(obj, float):
        raise TypeError("routing_evidence must not contain floats")
    if isinstance(obj, dict):
        for v in obj.values():
            _assert_no_floats(v)
    elif isinstance(obj, list):
        for item in obj:
            _assert_no_floats(item)


# ── Self-test ──────────────────────────────────────────────────────────────────


def _self_test() -> dict[str, Any]:
    mock_body: dict[str, Any] = {
        "intent_id": "0000000000000000000000000000000000000000000000000000000000000001",
        "writ_id": "0000000000000000000000000000000000000000000000000000000000000002",
        "plan": {"tool": "audio_transcribe", "args": {"uri": "0g://meeting.wav"}},
        "policy_trace": {
            "rules_evaluated": ["writ.authority"],
            "decision": {"kind": "permit"},
        },
        "status": {"kind": "staged"},
    }
    mock_ecu: dict[str, Any] = {
        "decision_id": "dec_thymos_adapter_001",
        "capability_id": "audio_transcription",
        "provider": "feishu_minutes",
        "execution_type": "api",
        "callable": True,
        "tool_key": "feishu_minutes",
        "reason": "capability_match",
        "confidence": 0.82,
        "explain": {
            "selected_capability": {
                "matched_capabilities": ["audio_transcription"],
            },
        },
        "trace": {
            "top_candidates": [
                {
                    "capability_id": "audio_transcription",
                    "provider": "feishu_minutes",
                    "score": 0.82,
                    "rank": 1,
                },
                {
                    "capability_id": "audio_transcription",
                    "provider": "tongyi_tingwu",
                    "score": 0.76,
                    "rank": 2,
                },
                {
                    "capability_id": "audio_transcription",
                    "provider": "openai",
                    "score": 0.71,
                    "rank": 3,
                },
            ],
        },
    }

    evidence = ThymosRoutingAdvisor(mock_ecu).to_evidence()
    assert evidence.confidence == 8200
    assert evidence.cost_estimate_usd == usd_to_millicents(0.18)
    assert evidence.selected == "audio_transcription/feishu_minutes"
    assert len(evidence.alternatives) == 2

    proposal_id_before = "prop_hash_placeholder"
    envelope_in = {"id": proposal_id_before, "body": mock_body}
    attached = attach_routing_evidence_to_proposal(envelope_in, evidence)

    assert attached["id"] == proposal_id_before
    assert attached["body"] == mock_body
    assert "routing_evidence" in attached
    assert "routing_evidence" not in attached["body"]
    _assert_no_floats(attached["routing_evidence"])

    replay_hash = compute_routing_decision_hash(
        selected=evidence.selected,
        alternatives=list(evidence.alternatives),
        reason_codes=list(evidence.reason_codes),
        confidence=evidence.confidence,
        latency_estimate_ms=evidence.latency_estimate_ms,
        cost_estimate_usd=evidence.cost_estimate_usd,
        fallback_hint=evidence.fallback_hint,
    )
    assert replay_hash == evidence.decision_hash

    bare_body_attach = attach_routing_evidence_to_proposal(mock_body, evidence)
    assert bare_body_attach["body"] == mock_body
    assert "routing_evidence" in bare_body_attach

    try:
        attach_routing_evidence_to_proposal(
            {"body": {**mock_body, "routing_evidence": {}}},
            evidence,
        )
    except ValueError as exc:
        assert "ProposalBody" in str(exc)
    else:
        raise AssertionError("expected ValueError for routing_evidence inside body")

    return attached


if __name__ == "__main__":
    import json as _json

    result = _self_test()
    print(_json.dumps(result, indent=2, ensure_ascii=False))
