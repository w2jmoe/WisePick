"""
Decision Engine for WisePick API v0.
Minimal, auditable decision infrastructure.
"""
import json
import math
import time
import uuid
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.models.tool_spec import ApiToolSpec
from app.schemas.decide import DecideRequest, DecideResponse
from app.services.bootstrap_rules import extract_capabilities, BOOTSTRAP_VERSION
from app.core.database import rollback_session
from app.core.logger import get_logger
from app.core.config import settings
from app.adapters.yantrik_adapter import get_cluster_health, health_score_multiplier

logger = get_logger("decision_engine")

NO_MATCH_REASON = "No matching capability found"
FALLBACK_UNKNOWN_TOOL_KEY = "fallback_unknown"

DEFAULT_TOOL_METRICS: dict[str, float | int] = {
    "success_rate": 0.5,
    "avg_latency_ms": 1000.0,
    "avg_token_cost": 1000.0,
    "avg_result_quality": 0.5,
    "feedback_count": 0,
}


@dataclass
class ScoredTool:
    tool: ApiToolSpec
    score: float
    matched_capabilities: list[str]
    base_score: float = 0.0
    efficacy: float = 1.0
    metrics: dict[str, Any] = field(default_factory=dict)
    score_breakdown: dict[str, Any] = field(default_factory=dict)


def _compute_efficacy(metrics: dict[str, Any]) -> tuple[float, dict[str, float]]:
    """
    Efficacy = result_quality / (log(max(latency_ms, 100)) * log(max(token_cost, 10))).
    Higher quality and lower latency/token cost → higher efficacy.
    """
    quality = float(metrics.get("avg_result_quality") or DEFAULT_TOOL_METRICS["avg_result_quality"])
    latency_ms = float(metrics.get("avg_latency_ms") or DEFAULT_TOOL_METRICS["avg_latency_ms"])
    token_cost = float(metrics.get("avg_token_cost") or DEFAULT_TOOL_METRICS["avg_token_cost"])
    norm_latency = math.log(max(latency_ms, 100))
    norm_token = math.log(max(token_cost, 10))
    denominator = norm_latency * norm_token
    if denominator <= 0:
        denominator = 1.0
    efficacy = quality / denominator
    detail = {
        "result_quality": round(quality, 4),
        "avg_latency_ms": round(latency_ms, 2),
        "avg_token_cost": round(token_cost, 2),
        "norm_latency_log": round(norm_latency, 4),
        "norm_token_cost_log": round(norm_token, 4),
        "efficacy_denominator": round(denominator, 4),
    }
    return round(efficacy, 6), detail


def _compute_score(
    tool: ApiToolSpec,
    target_capabilities: list[str],
    metrics: dict[str, Any],
) -> dict[str, Any]:
    """
    Final score = base_score * efficacy.

    base_score = capability_match * 0.70 + effective_success_rate * 0.20
                 + effective_bootstrap_weight * 0.10

    Low-match protection: if no capability matches, success_rate is heavily penalized.
    """
    tool_caps = _parse_tool_capabilities(tool.capabilities)
    capability_match = 1.0 if any(_capability_matches(cap, tool_caps) for cap in target_capabilities) else 0.0

    success_rate = float(metrics.get("success_rate") or DEFAULT_TOOL_METRICS["success_rate"])
    feedback_count = int(metrics.get("feedback_count") or 0)
    effective_success_rate = success_rate

    bootstrap_weight = getattr(tool, "bootstrap_weight", 0.5)
    effective_bootstrap_weight = float(bootstrap_weight) if bootstrap_weight is not None else 0.5
    effective_bootstrap_weight = _compute_effective_bootstrap_weight(
        effective_bootstrap_weight, feedback_count
    )

    if capability_match == 0.0:
        effective_success_rate = effective_success_rate * 0.1

    base_score = round(
        capability_match * 0.70
        + effective_success_rate * 0.20
        + effective_bootstrap_weight * 0.10,
        4,
    )

    efficacy, efficacy_detail = _compute_efficacy(metrics)
    final_score = round(base_score * efficacy, 4)

    return {
        "final_score": final_score,
        "base_score": base_score,
        "efficacy": efficacy,
        "capability_match": capability_match,
        "effective_success_rate": round(effective_success_rate, 4),
        "effective_bootstrap_weight": effective_bootstrap_weight,
        "efficacy_detail": efficacy_detail,
    }


def _parse_tool_capabilities(cap_string: str) -> set[str]:
    """Parse comma-separated capabilities string into set."""
    if not cap_string:
        return set()
    return {cap.strip().lower() for cap in cap_string.split(",") if cap.strip()}


def _capability_matches(target_cap: str, tool_caps: set[str]) -> bool:
    """Check if target capability matches any tool capability."""
    target_cap_normalized = target_cap.strip().lower()
    return any(target_cap_normalized == cap for cap in tool_caps)


# Bootstrap decay half-life: number of feedback records at which bootstrap weight is halved
# When feedback_count >= DECAY_HALF_LIFE, bootstrap_weight is reduced by 50% or more
DECAY_HALF_LIFE = 20


def _compute_effective_bootstrap_weight(bootstrap_weight: float, feedback_count: int) -> float:
    """
    Compute effective bootstrap weight with decay based on feedback count.
    
    Cold start (0 feedback):  effective = bootstrap_weight (full)
    Some feedback (20):       effective = bootstrap_weight * 0.5 (half)
    Lots of feedback (100):   effective → bootstrap_weight * 0.17 (near zero)
    
    Decay formula: decay_factor = 1 / (1 + feedback_count / DECAY_HALF_LIFE)
    """
    decay_factor = 1.0 / (1.0 + feedback_count / DECAY_HALF_LIFE)
    return round(bootstrap_weight * decay_factor, 4)


def _get_feedback_count(db: Session, tool_key: str) -> int:
    """
    Get total feedback count for a tool from the feedback table.
    
    Args:
        db: SQLAlchemy session
        tool_key: The tool identifier
        
    Returns:
        int: Number of feedback records for this tool, 0 if none
    """
    try:
        result = db.execute(
            text("SELECT COUNT(*) FROM feedback WHERE tool_key = :tool_key"),
            {"tool_key": tool_key}
        ).fetchone()
        
        if result and result[0] is not None:
            return int(result[0])
        return 0
    except Exception as e:
        rollback_session(db)
        logger.warning("Failed to get feedback count for %s: %s", tool_key, e)
        return 0


def _get_tool_metrics(db: Session, tool_key: str) -> dict[str, Any]:
    """
    Load aggregated ROI metrics from tool_stats for scoring.

    Returns defaults when the tool has no row or columns are null.
    """
    metrics: dict[str, Any] = dict(DEFAULT_TOOL_METRICS)
    try:
        result = db.execute(
            text("""
                SELECT success_rate, avg_latency_ms, avg_token_cost,
                       avg_result_quality, feedback_count
                FROM tool_stats
                WHERE tool_key = :tool_key
            """),
            {"tool_key": tool_key},
        ).fetchone()

        if not result:
            return metrics

        if result[0] is not None:
            metrics["success_rate"] = float(result[0])
        if result[1] is not None:
            metrics["avg_latency_ms"] = float(result[1])
        if result[2] is not None:
            metrics["avg_token_cost"] = float(result[2])
        if result[3] is not None:
            metrics["avg_result_quality"] = float(result[3])
        if result[4] is not None:
            metrics["feedback_count"] = int(result[4])
        return metrics
    except Exception as e:
        rollback_session(db)
        logger.warning("Failed to get tool metrics for %s: %s", tool_key, e)
        return metrics


def _should_reject_no_match(
    target_capabilities: list[str],
    scored_tools: list[ScoredTool],
) -> bool:
    """True when bootstrap rules found nothing or no registered tool matches."""
    if not target_capabilities:
        return True
    return all(
        (st.score_breakdown or {}).get("capability_match", 0) == 0
        for st in scored_tools
    )


def _build_no_match_explain(
    target_capabilities: list[str],
    scored_tools: list[ScoredTool],
) -> dict[str, Any]:
    return {
        "no_match": True,
        "reason_code": "no_matching_capability",
        "reason": NO_MATCH_REASON,
        "target_capabilities": target_capabilities,
        "candidate_count": len(scored_tools),
        "scoring_formula": (
            "Routing rejected: target_capabilities empty or all capability_match=0; "
            "runtime must fallback without forced tool_choice"
        ),
    }


def _build_no_match_trace(
    request: DecideRequest,
    scored_tools: list[ScoredTool],
    started_at: float,
    yantrik_meta: dict | None = None,
) -> dict[str, Any]:
    latency_ms = int((time.perf_counter() - started_at) * 1000)
    trace: dict[str, Any] = {
        "timestamp": time.time(),
        "latency_ms": latency_ms,
        "no_match": True,
        "top_candidates": [
            {
                "capability_id": (
                    tool.matched_capabilities[0]
                    if tool.matched_capabilities
                    else "general_capability"
                ),
                "provider": tool.tool.tool_key,
                "score": tool.score,
                "base_score": tool.base_score,
                "efficacy": tool.efficacy,
                "capability_match": (tool.score_breakdown or {}).get("capability_match", 0),
                "rank": i + 1,
            }
            for i, tool in enumerate(scored_tools[:5])
        ],
    }
    if yantrik_meta is not None:
        trace["yantrik_cluster"] = yantrik_meta
    return trace


def run_decision(request: DecideRequest, db: Session) -> DecideResponse:
    """
    Main decision function for WisePick API v0.
    Returns minimal, auditable decision response.
    """
    started_at = time.perf_counter()
    
    # Load all enabled tools
    tools = db.query(ApiToolSpec).filter(ApiToolSpec.enabled == True).all()
    
    if not tools:
        raise ValueError("No enabled tools available")
    
    # Extract capabilities using bootstrap rules
    target_capabilities = extract_capabilities(request.task)
    
    logger.info(f'processing decision: {len(tools)} tools, {len(target_capabilities)} capabilities')

    # Optional YantrikDB cluster health → ECU score multiplier (plugin-style; off when URL unset)
    yantrik_health = None
    health_mult = 1.0
    if (settings.YANTRIK_DB_URL or "").strip():
        yantrik_health = get_cluster_health(
            settings.YANTRIK_DB_URL.strip(),
            (settings.YANTRIK_DB_API_KEY or "").strip(),
        )
        health_mult = health_score_multiplier(yantrik_health)
    yantrik_meta = (
        {
            "configured": True,
            "replication_lag_log_entries": (
                yantrik_health.replication_lag_log_entries if yantrik_health else None
            ),
            "health_penalty_applied": health_mult < 1.0,
            "health_score_multiplier": health_mult,
        }
        if (settings.YANTRIK_DB_URL or "").strip()
        else {"configured": False}
    )
    
    # Score all tools
    scored_tools = []
    for tool in tools:
        metrics = _get_tool_metrics(db, tool.tool_key)
        breakdown = _compute_score(tool, target_capabilities, metrics)
        score = breakdown["final_score"] * health_mult

        tool_caps = _parse_tool_capabilities(tool.capabilities)
        matched_caps = [cap for cap in target_capabilities if _capability_matches(cap, tool_caps)]

        scored_tools.append(
            ScoredTool(
                tool=tool,
                score=score,
                matched_capabilities=matched_caps,
                base_score=breakdown["base_score"],
                efficacy=breakdown["efficacy"],
                metrics=metrics,
                score_breakdown=breakdown,
            )
        )
    
    # Sort by score descending (full float precision; tie-break by tool_key for determinism)
    scored_tools.sort(key=lambda x: (-x.score, x.tool.tool_key))
    
    if not scored_tools:
        raise ValueError("No tools matched the task requirements")

    if _should_reject_no_match(target_capabilities, scored_tools):
        logger.info(
            "no matching capability: task=%r target_capabilities=%s",
            request.task[:80],
            target_capabilities,
        )
        decision_id = f"dec_{uuid.uuid4().hex[:16]}"
        explain = _build_no_match_explain(target_capabilities, scored_tools)
        trace = _build_no_match_trace(request, scored_tools, started_at, yantrik_meta)
        _create_no_match_decision_log(db, decision_id, request, explain, trace)
        return DecideResponse(
            decision_id=decision_id,
            capability_id="",
            execution_type="api",
            provider="",
            callable=False,
            tool_key="",
            reason=NO_MATCH_REASON,
            confidence=0.0,
            explain=explain,
            trace=trace,
        )
    
    # Select top tool
    top_tool = scored_tools[0]
    
    # Log scoring details
    logger.info(
        f"top tool: {top_tool.tool.tool_key} score={top_tool.score:.4f} "
        f"base={top_tool.base_score:.4f} efficacy={top_tool.efficacy:.4f} "
        f"feedback_count={top_tool.metrics.get('feedback_count', 0)}"
    )
    
    # Generate decision ID
    decision_id = f"dec_{uuid.uuid4().hex[:16]}"
    
    # Build explanation
    reason = _build_reason(
        top_tool,
        target_capabilities,
        int(top_tool.metrics.get("feedback_count") or 0),
        yantrik_meta,
    )
    
    # Build explain and trace payloads
    explain = _build_explain_payload(top_tool, target_capabilities, scored_tools, yantrik_meta)
    trace = _build_trace_payload(request, top_tool, scored_tools, started_at, yantrik_meta)
    
    # Create decision log (simplified for v0)
    _create_decision_log(db, decision_id, request, top_tool, reason, explain, trace)
    
    # Build capability routing response with tool_key → capability_id mapping
    capability_id = _map_tool_key_to_capability_id(top_tool.tool, top_tool.matched_capabilities)
    
    return DecideResponse(
        decision_id=decision_id,
        capability_id=capability_id,
        execution_type="api",  # v0 default, future versions may support mcp, function_call
        provider=top_tool.tool.tool_key,
        callable=True,
        tool_key=top_tool.tool.tool_key,  # Legacy field maintained for backward compatibility
        reason=reason,
        confidence=top_tool.score,
        explain=explain,
        trace=trace
    )


def _map_tool_key_to_capability_id(tool: ApiToolSpec, matched_capabilities: list[str]) -> str:
    """
    Map tool_key to capability_id using capability mapping rules.
    
    Rules:
    - If tool has capability field → use primary matched capability
    - Otherwise fallback: capability_id = tool_key + "_capability"
    """
    if matched_capabilities:
        # Use the primary matched capability
        return matched_capabilities[0]
    else:
        # Fallback: tool_key + "_capability"
        return f"{tool.tool_key}_capability"


def _build_reason(
    top_tool: ScoredTool,
    target_capabilities: list[str],
    feedback_count: int = 0,
    yantrik_meta: dict | None = None,
) -> str:
    """Build human-readable reason for capability routing."""
    parts = []
    
    if target_capabilities:
        parts.append(f"Capability routing matched: {', '.join(target_capabilities)}")
    else:
        parts.append("Capability routing: general")
    
    if top_tool.matched_capabilities:
        parts.append(f"Selected capability: {', '.join(top_tool.matched_capabilities)}")
    
    # Compute effective bootstrap weight
    bootstrap_weight = float(getattr(top_tool.tool, 'bootstrap_weight', 0.5) or 0.5)
    effective_bootstrap = _compute_effective_bootstrap_weight(bootstrap_weight, feedback_count)
    parts.append(f"Effective bootstrap weight: {effective_bootstrap:.4f}")
    
    parts.append(f"Execution success rate: {_format_success_rate(top_tool.metrics)}")
    bd = top_tool.score_breakdown or {}
    ed = bd.get("efficacy_detail") or {}
    parts.append(f"Base score: {top_tool.base_score:.4f}")
    parts.append(
        f"Efficacy: {top_tool.efficacy:.4f} "
        f"(quality={ed.get('result_quality', 'n/a')}, "
        f"avg_latency_ms={ed.get('avg_latency_ms', 'n/a')}, "
        f"avg_token_cost={ed.get('avg_token_cost', 'n/a')})"
    )
    parts.append(f"Confidence score: {top_tool.score:.4f}")

    if (
        yantrik_meta
        and yantrik_meta.get("configured")
        and yantrik_meta.get("health_penalty_applied")
    ):
        lag = yantrik_meta.get("replication_lag_log_entries")
        mult = yantrik_meta.get("health_score_multiplier")
        parts.append(
            f"YantrikDB health penalty (replication_lag_log_entries={lag}); ECU scores scaled by {mult}"
        )
    
    return "; ".join(parts)


def _format_success_rate(metrics: dict[str, Any]) -> str:
    rate = metrics.get("success_rate")
    if rate is None:
        return "50% (default)"
    return f"{float(rate):.0%}"


def _build_explain_payload(
    top_tool: ScoredTool,
    target_capabilities: list[str],
    all_tools: list[ScoredTool],
    yantrik_meta: dict | None = None,
) -> dict:
    """Build explain payload for auditability."""
    metrics = top_tool.metrics or dict(DEFAULT_TOOL_METRICS)
    feedback_count = int(metrics.get("feedback_count") or 0)
    bootstrap_weight = float(getattr(top_tool.tool, "bootstrap_weight", 0.5) or 0.5)
    effective_bootstrap = _compute_effective_bootstrap_weight(bootstrap_weight, feedback_count)
    bd = top_tool.score_breakdown or {}
    ed = bd.get("efficacy_detail") or {}

    scoring_formula = (
        "(capability_match * 0.70 + execution_success_rate * 0.20 + effective_bootstrap_weight * 0.10) "
        "* efficacy; efficacy = result_quality / (log(max(avg_latency_ms, 100)) * log(max(avg_token_cost, 10)))"
    )
    if yantrik_meta and yantrik_meta.get("health_penalty_applied"):
        scoring_formula += (
            "; then multiply all ECU scores by yantrik health_score_multiplier when "
            "replication_lag_log_entries > 500"
        )

    out: dict[str, Any] = {
        "scoring_formula": scoring_formula,
        "selected_capability": {
            "capability_id": top_tool.matched_capabilities[0] if top_tool.matched_capabilities else "general_capability",
            "provider": top_tool.tool.tool_key,
            "score": top_tool.score,
            "base_score": top_tool.base_score,
            "efficacy": top_tool.efficacy,
            "matched_capabilities": top_tool.matched_capabilities,
            "roi_metrics": {
                "avg_latency_ms": metrics.get("avg_latency_ms"),
                "avg_token_cost": metrics.get("avg_token_cost"),
                "avg_result_quality": metrics.get("avg_result_quality"),
                "success_rate": metrics.get("success_rate"),
            },
            "efficacy_detail": ed,
        },
        "candidate_count": len(all_tools),
        "feedback_count": feedback_count,
        "effective_bootstrap_weight": effective_bootstrap,
        "score_breakdown": bd,
    }
    if yantrik_meta is not None:
        out["yantrik_cluster"] = yantrik_meta
    return out


def _build_trace_payload(
    request: DecideRequest,
    top_tool: ScoredTool,
    all_tools: list[ScoredTool],
    started_at: float,
    yantrik_meta: dict | None = None,
) -> dict:
    """Build trace payload for debugging."""
    latency_ms = int((time.perf_counter() - started_at) * 1000)
    
    trace: dict[str, Any] = {
        "timestamp": time.time(),
        "latency_ms": latency_ms,
        "top_candidates": [
            {
                "capability_id": tool.matched_capabilities[0] if tool.matched_capabilities else "general_capability",
                "provider": tool.tool.tool_key,
                "score": tool.score,
                "base_score": tool.base_score,
                "efficacy": tool.efficacy,
                "avg_latency_ms": (tool.metrics or {}).get("avg_latency_ms"),
                "avg_token_cost": (tool.metrics or {}).get("avg_token_cost"),
                "rank": i + 1,
            }
            for i, tool in enumerate(all_tools[:5])
        ],
    }
    if yantrik_meta is not None:
        trace["yantrik_cluster"] = yantrik_meta
    return trace


def _create_no_match_decision_log(
    db: Session,
    decision_id: str,
    request: DecideRequest,
    explain: dict,
    trace: dict,
) -> None:
    """Persist a no-match decision anchor for feedback and analytics."""
    try:
        db.execute(
            text("""
                INSERT INTO decisions
                (decision_id, task, context, constraints, selected_tool_key,
                 reason, confidence, explain, trace, bootstrap_version, created_at)
                VALUES
                (:decision_id, :task, :context, :constraints, :selected_tool_key,
                 :reason, :confidence, :explain, :trace, :bootstrap_version, :created_at)
            """),
            {
                "decision_id": decision_id,
                "task": request.task,
                "context": json.dumps(request.context or {}),
                "constraints": json.dumps(request.constraints or {}),
                "selected_tool_key": FALLBACK_UNKNOWN_TOOL_KEY,
                "reason": NO_MATCH_REASON,
                "confidence": 0.0,
                "explain": json.dumps(explain),
                "trace": json.dumps(trace),
                "bootstrap_version": BOOTSTRAP_VERSION,
                "created_at": datetime.utcnow(),
            },
        )
        db.commit()
    except Exception as e:
        rollback_session(db)
        logger.error("Failed to create no-match decision log: %s", e)
        raise


def _create_decision_log(db: Session, decision_id: str, request: DecideRequest, 
                         top_tool: ScoredTool, reason: str, explain: dict, trace: dict) -> None:
    """Create decision log entry."""
    # For v0, we'll use a simple approach - in a real implementation,
    # we would use the proper decision model
    try:
        db.execute(
            text("""
                INSERT INTO decisions 
                (decision_id, task, context, constraints, selected_tool_key, 
                 reason, confidence, explain, trace, bootstrap_version, created_at)
                VALUES 
                (:decision_id, :task, :context, :constraints, :selected_tool_key,
                 :reason, :confidence, :explain, :trace, :bootstrap_version, :created_at)
            """),
            {
                "decision_id": decision_id,
                "task": request.task,
                "context": json.dumps(request.context or {}),
                "constraints": json.dumps(request.constraints or {}),
                "selected_tool_key": top_tool.tool.tool_key,
                "reason": reason,
                "confidence": float(top_tool.score),
                "explain": json.dumps(explain),
                "trace": json.dumps(trace),
                "bootstrap_version": BOOTSTRAP_VERSION,
                "created_at": datetime.utcnow()
            }
        )
        db.commit()
    except Exception as e:
        rollback_session(db)
        logger.error("Failed to create decision log: %s", e)
        raise
