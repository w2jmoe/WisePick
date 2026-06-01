"""
WisePick → THYMOS adapter (Proposal Contract v1, Option 2).

Maps WisePick ECU / routing outcomes to THYMOS ``RoutingEvidence`` and attaches it
at the **Proposal** envelope — never inside ``ProposalBody`` — so
``ProposalId = blake3(canonical_json(ProposalBody))`` is unchanged.

RFC: OpenThymos ``docs/rfcs/proposal-contract-v1.md`` (Accepted); provider routing
metadata via ``routing_evidence`` on ``Proposal``, outside the content-addressed body.

Optional HTTP pull for OpenThymos ``GET /runs/{id}/routing-outcomes`` via ``ThymosClient``
(pinned to **open-thymos v0.4.4** — response is a top-level JSON array); WisePick feedback
closure via ``ThymosFeedbackConnector``.
"""

from __future__ import annotations

import copy
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping, Protocol, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from adapters.utils import (
    BASIS_POINTS_SCALE,
    assert_no_floats,
    build_reason_codes_from_decide,
    confidence_to_basis_points,
    normalize_capability_id,
    normalize_provider,
    usd_to_millicents,
)
from app.schemas.decide import DecideResponse

# Integration contract: open-thymos v0.4.4 (routing-outcomes returns a JSON array).
OPEN_THYMOS_INTEGRATION_VERSION = "v0.4.4"

THYMOS_ROUTE_LABEL_SEP = ":"
THYMOS_ROUTING_OUTCOME_SCHEMA = "wisepick.thymos.routing_outcome.v1"


def format_thymos_route_label(provider: str, capability_id: str) -> str:
    """OpenThymos wire label: ``{provider}:{capability_id}`` (normalized)."""
    prov = normalize_provider(provider)
    cap = normalize_capability_id(capability_id)
    if not cap or not prov:
        raise ValueError("capability_id and provider are required for THYMOS route label")
    return f"{prov}{THYMOS_ROUTE_LABEL_SEP}{cap}"


class FallbackHint(BaseModel):
    """THYMOS fallback topology hint; carried in ``RoutingEvidence`` only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(..., min_length=1)
    model: str | None = Field(
        default=None,
        min_length=1,
        description="Optional capability / route model id (not an LLM name).",
    )
    reason: str = Field(..., min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _normalize_tokens(cls, data: Any) -> Any:
        if isinstance(data, dict):
            out = dict(data)
            if "provider" in out:
                out["provider"] = normalize_provider(str(out["provider"]))
            if out.get("model") is not None:
                out["model"] = normalize_capability_id(str(out["model"]))
            return out
        return data


class RoutingEvidence(BaseModel):
    """
    Provider routing metadata for THYMOS proposal stage (outside ``ProposalBody``).

    All numeric fields are integers — no floats on the replay/canonical surface.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_hash: str = Field(..., min_length=64, max_length=64)
    selected: str = Field(..., min_length=1)
    alternatives: list[str] = Field(default_factory=list)
    confidence_bps: int = Field(
        ...,
        ge=0,
        le=BASIS_POINTS_SCALE,
    )
    reason_codes: list[str] = Field(..., min_length=1)
    latency_estimate_ms: int = Field(..., ge=0)
    cost_estimate_millicents: int = Field(
        ...,
        ge=0,
        description="USD millicents (1 USD = 100_000).",
    )
    fallback_hint: FallbackHint | None = None

    @model_validator(mode="after")
    def _selected_not_in_alternatives(self) -> RoutingEvidence:
        if self.selected in self.alternatives:
            raise ValueError("alternatives must not include selected route label")
        return self


class RoutingOutcome(BaseModel):
    """Telemetry-safe THYMOS routing outcome (OpenThymos v0.4.4 pull surface)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_hash: str = Field(..., min_length=1)
    selected: str = Field(..., min_length=1)
    status: str = Field(..., min_length=1)
    latency_ms: int = Field(..., ge=0)


class WisePickFeedbackLike(Protocol):
    def feedback(
        self,
        decision_id: str,
        success: bool,
        latency_ms: int,
        *,
        user_note: str | None = None,
    ) -> dict: ...


def parse_routing_outcome(raw: Mapping[str, Any]) -> RoutingOutcome:
    """Parse one ``/routing-outcomes`` record (integer-only, no floats)."""
    return RoutingOutcome(
        decision_hash=str(raw["decision_hash"]),
        selected=str(raw["selected"]),
        status=str(raw["status"]),
        latency_ms=int(raw["latency_ms"]),
    )


def routing_outcome_to_feedback(
    outcome: RoutingOutcome,
    *,
    decision_id: str,
) -> dict[str, Any]:
    """Map a THYMOS outcome to WisePick ``POST /v1/feedback`` kwargs."""
    note = json.dumps(
        {
            "schema": THYMOS_ROUTING_OUTCOME_SCHEMA,
            "decision_hash": outcome.decision_hash,
            "selected": outcome.selected,
            "status": outcome.status,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return {
        "decision_id": decision_id,
        "success": outcome.status == "committed",
        "latency_ms": outcome.latency_ms,
        "user_note": note,
    }


def _normalize_routing_outcomes_body(data: Any) -> list[Any]:
    """
    Normalize ``GET /runs/{id}/routing-outcomes`` JSON body.

    open-thymos v0.4.4 returns a top-level array. v0.4.3 wrapped records in
    ``{"outcomes": [...]}`` — still accepted for local/dev compatibility.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        wrapped = data.get("outcomes")
        if isinstance(wrapped, list):
            return wrapped
    return []


def _wire_routing_outcomes(raw_items: list[Any]) -> list[dict[str, Any]]:
    """Parse raw outcome objects into integer-only wire dicts."""
    parsed: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        try:
            wire = parse_routing_outcome(item).model_dump(mode="json")
            assert_no_floats(wire)
            parsed.append(wire)
        except (KeyError, TypeError, ValueError):
            continue
    return parsed


class ThymosClient:
    """
    Lightweight OpenThymos HTTP client (stdlib ``urllib`` only).

    Depends on open-thymos **v0.4.4** for ``GET /runs/{id}/routing-outcomes``,
    which returns a telemetry-safe JSON **array** of routing outcome records.
    """

    def __init__(self, api_base_url: str, *, timeout: float = 30.0) -> None:
        self._base = api_base_url.rstrip("/")
        self._timeout = timeout

    def _get_json(self, path: str) -> Any:
        req = urllib.request.Request(f"{self._base}{path}", method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def fetch_routing_outcomes(self, trajectory_id: str) -> dict[str, Any]:
        """
        GET ``/runs/{id_or_trajectory}/routing-outcomes`` (open-thymos v0.4.4).

        v0.4.4 response body is a JSON array:
        ``[{decision_hash, selected, status, latency_ms}, ...]``.

        Returns a normalized envelope ``{"outcomes": [...]}`` for local processors.
        Accepts either a run id or the trajectory hex from ``/routed-submit``.
        """
        run_ref = (trajectory_id or "").strip()
        if not run_ref:
            return {"outcomes": []}
        path = f"/runs/{urllib.parse.quote(run_ref, safe='')}/routing-outcomes"
        data = self._get_json(path)
        if data is None:
            return {"outcomes": []}
        return {"outcomes": _wire_routing_outcomes(_normalize_routing_outcomes_body(data))}


class ThymosFeedbackConnector:
    """
    Join THYMOS routing outcomes to WisePick feedback via ``decision_hash``.

    Register ``decision_hash → decision_id`` when attaching routing evidence so
    telemetry pulls can close the learning loop without workload leakage.
    """

    def __init__(
        self,
        wisepick: WisePickFeedbackLike,
        decision_hash_index: Mapping[str, str] | None = None,
    ) -> None:
        self._wp = wisepick
        self._index = {
            (h or "").strip(): (d or "").strip()
            for h, d in (decision_hash_index or {}).items()
            if (h or "").strip() and (d or "").strip()
        }

    def register_decision(self, decision_hash: str, decision_id: str) -> None:
        h = (decision_hash or "").strip()
        d = (decision_id or "").strip()
        if h and d:
            self._index[h] = d

    def process_outcomes(self, outcomes_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Send WisePick feedback for outcomes whose ``decision_hash`` is registered."""
        raw = outcomes_payload.get("outcomes")
        if not isinstance(raw, list):
            return []
        sent: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                outcome = parse_routing_outcome(item)
            except (KeyError, TypeError, ValueError):
                continue
            decision_id = self._index.get(outcome.decision_hash)
            if not decision_id:
                continue
            fb = self._wp.feedback(**routing_outcome_to_feedback(outcome, decision_id=decision_id))
            sent.append(
                {
                    "decision_hash": outcome.decision_hash,
                    "decision_id": decision_id,
                    "feedback": fb,
                }
            )
        return sent

    def fetch_and_process(self, client: ThymosClient, trajectory_id: str) -> list[dict[str, Any]]:
        """Pull routing outcomes from THYMOS and forward matched rows to WisePick."""
        return self.process_outcomes(client.fetch_routing_outcomes(trajectory_id))


def compute_routing_decision_hash(
    *,
    selected: str,
    alternatives: list[str],
    reason_codes: list[str],
    confidence_bps: int,
    latency_estimate_ms: int,
    cost_estimate_millicents: int,
    fallback_hint: FallbackHint | None = None,
) -> str:
    """
    Replay-stable SHA-256 over integer-only routing fields.

    Excludes ephemeral WisePick ``decision_id`` and any float-derived wire values.
    """
    preimage_obj: dict[str, Any] = {
        "selected": selected,
        "alternatives": list(alternatives),
        "reason_codes": sorted(reason_codes),
        "confidence_bps": int(confidence_bps),
        "latency_estimate_ms": int(latency_estimate_ms),
        "cost_estimate_millicents": int(cost_estimate_millicents),
    }
    if fallback_hint is not None:
        preimage_obj["fallback_hint"] = fallback_hint.model_dump(mode="json", exclude_none=True)
    preimage = json.dumps(
        preimage_obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(preimage.encode("utf-8")).hexdigest()


def _coerce_decide_response(decision: Union[DecideResponse, dict[str, Any]]) -> DecideResponse:
    if isinstance(decision, DecideResponse):
        return decision
    if isinstance(decision, dict):
        return DecideResponse(**decision)
    raise TypeError("decision must be DecideResponse or dict")


def _ranked_pairs_from_ecu(ecu: Mapping[str, Any]) -> list[tuple[str, str, int]]:
    """Return [(capability_id, provider, rank), ...] sorted by rank (normalized)."""
    trace = ecu.get("trace") if isinstance(ecu.get("trace"), dict) else {}
    raw = trace.get("top_candidates")
    rows: list[tuple[str, str, int]] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            cap = normalize_capability_id(str(item.get("capability_id") or ""))
            prov = normalize_provider(str(item.get("provider") or item.get("tool_key") or ""))
            if not cap or not prov:
                continue
            rows.append((cap, prov, int(item.get("rank") or len(rows) + 1)))
    if not rows:
        cap = normalize_capability_id(str(ecu.get("capability_id") or ""))
        prov = normalize_provider(str(ecu.get("provider") or ecu.get("tool_key") or ""))
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
    """Return (latency_estimate_ms, cost_estimate_millicents)."""
    cap = normalize_capability_id(capability_id)
    prov = normalize_provider(provider)
    base_latency = {
        "audio_transcription": 45_000,
        "general_content": 8_000,
    }.get(cap, 15_000)
    base_cost_usd = {
        ("audio_transcription", "feishu_minutes"): 0.18,
        ("audio_transcription", "tongyi_tingwu"): 0.22,
        ("audio_transcription", "openai"): 0.35,
    }.get((cap, prov), 0.12)
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
        selected_label = format_thymos_route_label(prov0, cap0)
        alt_labels = [format_thymos_route_label(p, c) for c, p, _ in ranked[1:3]]

        explain = self._decision.explain if isinstance(self._decision.explain, dict) else {}
        reason_codes = build_reason_codes_from_decide(
            callable=self._decision.callable,
            confidence=self._decision.confidence,
            capability_id=self._decision.capability_id,
            explain=explain,
        )
        confidence_bps = confidence_to_basis_points(self._decision.confidence)
        latency_ms, cost_mc = _estimate_cost_latency(cap0, prov0, constraints=self._constraints)

        hint: FallbackHint | None = None
        if len(ranked) > 1:
            cap_alt, prov_alt, _ = ranked[1]
            hint = FallbackHint(
                provider=prov_alt,
                model=cap_alt,
                reason=self._fallback_reason,
            )

        decision_hash = compute_routing_decision_hash(
            selected=selected_label,
            alternatives=alt_labels,
            reason_codes=reason_codes,
            confidence_bps=confidence_bps,
            latency_estimate_ms=latency_ms,
            cost_estimate_millicents=cost_mc,
            fallback_hint=hint,
        )

        return RoutingEvidence(
            decision_hash=decision_hash,
            selected=selected_label,
            alternatives=alt_labels,
            confidence_bps=confidence_bps,
            reason_codes=reason_codes,
            latency_estimate_ms=latency_ms,
            cost_estimate_millicents=cost_mc,
            fallback_hint=hint,
        )


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


def routing_evidence_to_wire(evidence: RoutingEvidence) -> dict[str, Any]:
    """Serialize ``RoutingEvidence`` for OpenThymos ``/routed-submit`` (integer-only, no aliases)."""
    return evidence.model_dump(mode="json", exclude_none=True)


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

    wire = routing_evidence_to_wire(evidence)
    assert_no_floats(wire)

    out = {**envelope, "routing_evidence": wire}
    if "routing_evidence" in out.get("body", {}):
        raise RuntimeError("internal error: routing_evidence leaked into ProposalBody")
    return out


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
    assert evidence.confidence_bps == 8200
    assert evidence.cost_estimate_millicents == usd_to_millicents(0.18)
    assert evidence.selected == "feishu_minutes:audio_transcription"
    assert evidence.alternatives == [
        "tongyi_tingwu:audio_transcription",
        "openai:audio_transcription",
    ]
    assert len(evidence.alternatives) == 2

    proposal_id_before = "prop_hash_placeholder"
    envelope_in = {"id": proposal_id_before, "body": mock_body}
    attached = attach_routing_evidence_to_proposal(envelope_in, evidence)

    assert attached["id"] == proposal_id_before
    assert attached["body"] == mock_body
    assert "routing_evidence" in attached
    assert "routing_evidence" not in attached["body"]
    wire_ev = attached["routing_evidence"]
    assert wire_ev["confidence_bps"] == 8200
    assert wire_ev["cost_estimate_millicents"] == usd_to_millicents(0.18)
    assert "confidence" not in wire_ev
    assert "cost_estimate_usd" not in wire_ev
    assert wire_ev["fallback_hint"]["provider"] == "tongyi_tingwu"
    assert wire_ev["fallback_hint"]["model"] == "audio_transcription"
    assert_no_floats(wire_ev)

    replay_hash = compute_routing_decision_hash(
        selected=evidence.selected,
        alternatives=list(evidence.alternatives),
        reason_codes=list(evidence.reason_codes),
        confidence_bps=evidence.confidence_bps,
        latency_estimate_ms=evidence.latency_estimate_ms,
        cost_estimate_millicents=evidence.cost_estimate_millicents,
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

    mock_outcome = {
        "decision_hash": evidence.decision_hash,
        "selected": evidence.selected,
        "status": "committed",
        "latency_ms": 42,
    }
    parsed = parse_routing_outcome(mock_outcome)
    assert parsed.latency_ms == 42
    assert_no_floats(parsed.model_dump(mode="json"))

    fb_kwargs = routing_outcome_to_feedback(parsed, decision_id=mock_ecu["decision_id"])
    assert fb_kwargs["success"] is True
    assert fb_kwargs["latency_ms"] == 42
    assert mock_ecu["decision_id"] in fb_kwargs["decision_id"]

    class _MockWP:
        def __init__(self) -> None:
            self.feedback_calls: list[dict[str, Any]] = []

        def feedback(self, decision_id: str, success: bool, latency_ms: int, *, user_note: str | None = None) -> dict:
            row = {
                "decision_id": decision_id,
                "success": success,
                "latency_ms": latency_ms,
                "user_note": user_note,
            }
            self.feedback_calls.append(row)
            return {"ok": True}

    mock_wp = _MockWP()
    connector = ThymosFeedbackConnector(mock_wp)
    connector.register_decision(evidence.decision_hash, mock_ecu["decision_id"])
    sent = connector.process_outcomes({"outcomes": [mock_outcome]})
    assert len(sent) == 1
    assert sent[0]["decision_hash"] == evidence.decision_hash
    assert len(mock_wp.feedback_calls) == 1
    assert mock_wp.feedback_calls[0]["latency_ms"] == 42

    wire_after = routing_evidence_to_wire(evidence)
    assert wire_after["confidence_bps"] == 8200
    assert wire_after["cost_estimate_millicents"] == usd_to_millicents(0.18)
    assert_no_floats(wire_after)

    v044_array = [
        {
            "decision_hash": evidence.decision_hash,
            "selected": evidence.selected,
            "status": "committed",
            "latency_ms": 99,
        }
    ]
    wired = _wire_routing_outcomes(_normalize_routing_outcomes_body(v044_array))
    assert len(wired) == 1
    assert wired[0]["latency_ms"] == 99

    return attached


if __name__ == "__main__":
    import json as _json

    result = _self_test()
    print(_json.dumps(result, indent=2, ensure_ascii=False))
