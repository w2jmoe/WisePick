"""
WisePick routing advisor artifact -> THYMOS proposal stage (stdlib only, no HTTP).

Models structured routing evidence before governed execution. Does not invoke
tools, run THYMOS, or own orchestration/retries.

Run from repo root:

  python examples/thymos_routing_advisor_demo.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

THYMOS_ROUTING_ADVISOR_SCHEMA = "wisepick.routing_advisor.thymos.v1"
THYMOS_PROPOSAL_SCHEMA = "thymos.proposal.v1"

_FALLBACK_CAPABILITY_IDS = frozenset({"none", "general_capability", ""})
_LOW_CONFIDENCE_THRESHOLD = 0.01

# Simulated intent (would be user/task text at proposal time).
INTENT = "Transcribe the board meeting recording and produce a compliance summary"
CONSTRAINTS: Dict[str, Any] = {
    "max_cost_usd": 2.50,
    "latency_budget_ms": 120_000,
    "data_classification": "internal",
}


def _normalize_intent(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _build_reason_codes(ecu: Mapping[str, Any]) -> List[str]:
    if not bool(ecu.get("callable", True)):
        return ["fallback_routing"]
    confidence = float(ecu.get("confidence") or 0.0)
    if confidence < _LOW_CONFIDENCE_THRESHOLD:
        return ["fallback_routing"]
    explain = ecu.get("explain") if isinstance(ecu.get("explain"), dict) else {}
    selected = explain.get("selected_capability")
    if isinstance(selected, dict) and selected.get("matched_capabilities"):
        return ["capability_match"]
    cap = str(ecu.get("capability_id") or "").strip()
    if cap and cap not in _FALLBACK_CAPABILITY_IDS:
        return ["capability_match"]
    return ["fallback_routing"]


@dataclass(frozen=True)
class RouteCandidate:
    capability_id: str
    provider: str
    score: float
    rank: int


@dataclass(frozen=True)
class FallbackPolicy:
    """
    THYMOS-owned execution topology uses this hint at proposal time.

    Modes (examples):
      fail_closed       - reject proposal if primary path unavailable
      fail_open         - allow degraded/default handler after governance
      use_alternative   - prefer ranked alternative on primary failure
      cached_decision   - rehydrate prior artifact by decision_hash
    """

    mode: str
    alternative_rank: Optional[int] = None
    notes: str = ""


@dataclass
class ThymosRoutingArtifact:
    schema_version: str
    decision_hash: str
    selected: RouteCandidate
    confidence: float
    reason_codes: List[str]
    latency_estimate_ms: int
    cost_estimate_usd: float
    alternatives: List[RouteCandidate] = field(default_factory=list)
    fallback_policy: FallbackPolicy = field(
        default_factory=lambda: FallbackPolicy(mode="use_alternative", alternative_rank=2)
    )
    governance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "decision_hash": self.decision_hash,
            "selected": asdict(self.selected),
            "confidence": round(self.confidence, 4),
            "reason_codes": list(self.reason_codes),
            "latency_estimate_ms": self.latency_estimate_ms,
            "cost_estimate_usd": round(self.cost_estimate_usd, 4),
            "alternatives": [asdict(c) for c in self.alternatives],
            "fallback_policy": asdict(self.fallback_policy),
            "governance": dict(self.governance),
        }


def _estimate_cost_latency(
    capability_id: str,
    provider: str,
    *,
    constraints: Mapping[str, Any] | None,
) -> tuple[int, float]:
    """Demo stand-in for registry-derived estimates (not live pricing APIs)."""
    base_latency = {
        "audio_transcription": 45_000,
        "general_content": 8_000,
    }.get(capability_id, 15_000)
    base_cost = {
        ("audio_transcription", "feishu_minutes"): 0.18,
        ("audio_transcription", "tongyi_tingwu"): 0.22,
        ("audio_transcription", "openai"): 0.35,
    }.get((capability_id, provider), 0.12)
    budget_ms = constraints.get("latency_budget_ms") if constraints else None
    if isinstance(budget_ms, (int, float)) and budget_ms > 0:
        base_latency = min(int(base_latency), int(budget_ms))
    ceiling = constraints.get("max_cost_usd") if constraints else None
    if isinstance(ceiling, (int, float)) and ceiling > 0:
        base_cost = min(float(base_cost), float(ceiling))
    return base_latency, base_cost


def _ranked_candidates_from_ecu(ecu: Mapping[str, Any]) -> List[RouteCandidate]:
    trace = ecu.get("trace") if isinstance(ecu.get("trace"), dict) else {}
    raw = trace.get("top_candidates")
    out: List[RouteCandidate] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            cap = str(item.get("capability_id") or "").strip()
            prov = str(item.get("provider") or item.get("tool_key") or "").strip()
            if not cap or not prov:
                continue
            out.append(
                RouteCandidate(
                    capability_id=cap,
                    provider=prov,
                    score=round(float(item.get("score", 0.0)), 4),
                    rank=int(item.get("rank") or len(out) + 1),
                )
            )
    if not out:
        cap = str(ecu.get("capability_id") or "").strip()
        prov = str(ecu.get("provider") or ecu.get("tool_key") or "").strip()
        if cap and prov:
            out.append(
                RouteCandidate(
                    capability_id=cap,
                    provider=prov,
                    score=round(float(ecu.get("confidence") or 0.0), 4),
                    rank=1,
                )
            )
    out.sort(key=lambda c: c.rank)
    return out


def compute_decision_hash(
    *,
    schema_version: str,
    intent: str,
    selected: RouteCandidate,
    alternatives: List[RouteCandidate],
    reason_codes: List[str],
    fallback_policy: FallbackPolicy,
    constraints: Mapping[str, Any] | None = None,
) -> str:
    """
    Replay-stable digest for ledger/rehydration.

    Binds intent + ranked path choices + policy hint. Excludes ephemeral
    decision_id and non-deterministic estimate fields.
    """
    preimage_obj: Dict[str, Any] = {
        "schema_version": schema_version,
        "intent": _normalize_intent(intent),
        "selected": asdict(selected),
        "alternatives": [asdict(c) for c in alternatives],
        "reason_codes": sorted(reason_codes),
        "fallback_policy": {
            "mode": fallback_policy.mode,
            "alternative_rank": fallback_policy.alternative_rank,
        },
        "constraints": dict(constraints or {}),
    }
    preimage = json.dumps(
        preimage_obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(preimage.encode("utf-8")).hexdigest()


class ThymosRoutingAdvisor:
    """
    Experimental artifact mapper (discussion/demo only).

    Mirrors the narrow advisor pattern used by AetherisRoutingAdvisor: translate a
    WisePick ECU-shaped dict into a replay-serializable evidence bundle for a
    downstream runtime — here THYMOS proposal intake, not execution.
    """

    def __init__(
        self,
        ecu: Mapping[str, Any],
        *,
        intent: str,
        constraints: Mapping[str, Any] | None = None,
        fallback_policy: FallbackPolicy | None = None,
    ) -> None:
        self._ecu = ecu
        self._intent = intent
        self._constraints = dict(constraints or {})
        self._fallback_policy = fallback_policy or FallbackPolicy(
            mode="use_alternative",
            alternative_rank=2,
            notes="Primary provider timeout -> rank-2 alternative after governance",
        )

    def to_artifact(self) -> ThymosRoutingArtifact:
        ranked = _ranked_candidates_from_ecu(self._ecu)
        if not ranked:
            raise ValueError("ECU must expose at least one ranked candidate")
        selected = ranked[0]
        alternatives = ranked[1:3]
        reason_codes = _build_reason_codes(self._ecu)
        latency_ms, cost_usd = _estimate_cost_latency(
            selected.capability_id,
            selected.provider,
            constraints=self._constraints,
        )
        decision_hash = compute_decision_hash(
            schema_version=THYMOS_ROUTING_ADVISOR_SCHEMA,
            intent=self._intent,
            selected=selected,
            alternatives=alternatives,
            reason_codes=reason_codes,
            fallback_policy=self._fallback_policy,
            constraints=self._constraints,
        )
        governance = {
            "decision_id": str(self._ecu.get("decision_id") or ""),
            "callable": bool(self._ecu.get("callable", True)),
            "execution_type": str(self._ecu.get("execution_type") or "api"),
            "constraint_snapshot": dict(self._constraints),
            "replay_key": decision_hash,
            "advisor_only": True,
        }
        return ThymosRoutingArtifact(
            schema_version=THYMOS_ROUTING_ADVISOR_SCHEMA,
            decision_hash=decision_hash,
            selected=selected,
            confidence=float(self._ecu.get("confidence") or selected.score),
            reason_codes=reason_codes,
            latency_estimate_ms=latency_ms,
            cost_estimate_usd=cost_usd,
            alternatives=alternatives,
            fallback_policy=self._fallback_policy,
            governance=governance,
        )


def build_thymos_proposal_input(
    *,
    intent: str,
    artifact: ThymosRoutingArtifact,
    constraints: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Example THYMOS proposal-stage payload (governance checks not yet run)."""
    return {
        "schema": THYMOS_PROPOSAL_SCHEMA,
        "stage": "proposal",
        "intent": _normalize_intent(intent),
        "constraints": dict(constraints or {}),
        "routing_evidence": {
            "schema_version": artifact.schema_version,
            "decision_hash": artifact.decision_hash,
            "selected": asdict(artifact.selected),
            "alternatives": [asdict(c) for c in artifact.alternatives],
            "confidence": round(artifact.confidence, 4),
            "reason_codes": list(artifact.reason_codes),
            "latency_estimate_ms": artifact.latency_estimate_ms,
            "cost_estimate_usd": round(artifact.cost_estimate_usd, 4),
            "fallback_policy": asdict(artifact.fallback_policy),
        },
        "governance_checks_pending": [
            "budget_ceiling",
            "data_classification",
            "provider_allowlist",
        ],
        "execution_deferred": True,
        "notes": "WisePick recommends paths; THYMOS owns approval, retries, and invoke topology.",
    }


def _simulated_wisepick_ecu() -> Dict[str, Any]:
    """Primary ECU plus two ranked alternatives (trace.top_candidates)."""
    return {
        "decision_id": "dec_thymos_demo_001",
        "capability_id": "audio_transcription",
        "provider": "feishu_minutes",
        "execution_type": "api",
        "callable": True,
        "tool_key": "feishu_minutes",
        "reason": "Capability routing matched: audio_transcription",
        "confidence": 0.82,
        "explain": {
            "selected_capability": {
                "capability_id": "audio_transcription",
                "provider": "feishu_minutes",
                "score": 0.82,
                "matched_capabilities": ["audio_transcription"],
            },
        },
        "trace": {
            "latency_ms": 4,
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


def _section(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


def main() -> None:
    ecu = _simulated_wisepick_ecu()
    advisor = ThymosRoutingAdvisor(
        ecu,
        intent=INTENT,
        constraints=CONSTRAINTS,
        fallback_policy=FallbackPolicy(
            mode="use_alternative",
            alternative_rank=2,
            notes="On primary failure, THYMOS may promote rank-2 after budget/policy pass",
        ),
    )
    artifact = advisor.to_artifact()
    artifact_dict = artifact.to_dict()

    # Replay-safe: recompute hash from stable fields must match serialized artifact.
    replay_hash = compute_decision_hash(
        schema_version=artifact.schema_version,
        intent=INTENT,
        selected=artifact.selected,
        alternatives=artifact.alternatives,
        reason_codes=artifact.reason_codes,
        fallback_policy=artifact.fallback_policy,
        constraints=CONSTRAINTS,
    )
    if replay_hash != artifact.decision_hash:
        raise SystemExit("decision_hash replay check failed")

    _section("1. Intent")
    print(INTENT)
    print(json.dumps({"constraints": CONSTRAINTS}, indent=2, ensure_ascii=False))

    _section("2. Routing advisor artifact (JSON)")
    print(json.dumps(artifact_dict, indent=2, ensure_ascii=False))

    proposal = build_thymos_proposal_input(
        intent=INTENT,
        artifact=artifact,
        constraints=CONSTRAINTS,
    )
    _section("3. Example THYMOS proposal input")
    print(json.dumps(proposal, indent=2, ensure_ascii=False))

    _section("Fallback policy examples (reference)")
    for mode in ("fail_closed", "fail_open", "use_alternative", "cached_decision"):
        sample = FallbackPolicy(mode=mode, notes=f"mode={mode}")
        print(f"  - {mode}: {json.dumps(asdict(sample), ensure_ascii=False)}")

    print("\nReplay check: decision_hash stable across re-serialization -> PASS")


if __name__ == "__main__":
    main()
