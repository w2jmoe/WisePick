import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.decision_dataset import DecisionDatasetRecord
from app.models.decision_log import ApiDecisionLog
from app.schemas.decide import DecideRequest

DATASET_SCHEMA_VERSION = 1
RULE_VERSION = "rules.v1"


def _json_safe(obj: Any) -> Any:
    return json.loads(json.dumps(obj, ensure_ascii=False, default=str))


def _as_dict(value: Any, default: dict | None = None) -> dict:
    if isinstance(value, dict):
        return value
    return default or {}


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    return []


def _extract_candidate_rows(candidate_tools: Any) -> list[dict]:
    payload = _as_dict(candidate_tools)
    eligible = _as_list(payload.get("eligible"))
    if eligible:
        return eligible
    return _as_list(payload.get("decision_ordered_top"))


def build_decision_dataset_record(
    *,
    request: DecideRequest,
    log: ApiDecisionLog,
    latency_ms: int,
) -> DecisionDatasetRecord:
    detected = _as_dict(log.detected_capabilities)
    candidate_tools = _as_dict(log.candidate_tools)
    filtered_out = _as_dict(log.filtered_out_tools)
    selection_path = _as_dict(detected.get("selection_path"))

    capabilities = _as_list(detected.get("capabilities"))
    raw_tools = _as_list(detected.get("raw_tools"))
    filtered_tools = _as_list(filtered_out.get("items"))
    scored_tools = _extract_candidate_rows(candidate_tools)

    fallbacks = _as_list(log.fallback_plan)
    primary = {
        "tool_key": log.chosen_tool,
        "confidence": float(log.confidence),
        "selection_path": selection_path,
    }

    dataset_payload = {
        "input": {
            "task": request.task,
            "context": request.context or {},
            "constraints": request.constraints or {},
            "caller": {},
        },
        "interpretation": {
            "capabilities": capabilities,
            "intent_confidence": float(log.confidence),
            "intent_unclear": bool(
                detected.get("intent_unclear", len(capabilities) == 0)
            ),
            "schema_version": DATASET_SCHEMA_VERSION,
        },
        "candidate_set": {
            "raw_tools": raw_tools,
            "filtered_tools": filtered_tools,
            "scored_tools": scored_tools,
        },
        "decision": {
            "strategy": selection_path.get(
                "strategy", detected.get("pool_strategy", "unknown")
            ),
            "score_threshold": float(selection_path.get("score_threshold", 0.0)),
            "primary": primary,
            "fallbacks": fallbacks,
            "relaxed_used": bool(selection_path.get("relaxation_used", False)),
            "final_candidate_count": int(
                _as_dict(detected.get("pipeline_steps")).get(
                    "final_count", len(scored_tools)
                )
            ),
        },
        "execution_meta": {
            "latency_ms": int(latency_ms),
            "model_used": False,
            "rule_version": RULE_VERSION,
        },
        "outcome": {
            "success": None,
            "user_feedback": None,
        },
    }

    safe_payload = _json_safe(dataset_payload)
    return DecisionDatasetRecord(
        decision_id=log.decision_id,
        input=safe_payload["input"],
        interpretation=safe_payload["interpretation"],
        candidate_set=safe_payload["candidate_set"],
        decision=safe_payload["decision"],
        execution_meta=safe_payload["execution_meta"],
        outcome=safe_payload["outcome"],
    )


def write_decision_dataset_fail_safe(
    *,
    db: Session,
    request: DecideRequest,
    log: ApiDecisionLog,
    latency_ms: int,
) -> None:
    try:
        record = build_decision_dataset_record(
            request=request,
            log=log,
            latency_ms=latency_ms,
        )
        db.add(record)
        db.commit()
    except Exception:
        db.rollback()
