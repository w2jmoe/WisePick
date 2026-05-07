"""
Decision Engine for WisePick API v0.
Minimal, auditable decision infrastructure.
"""
import json
import time
import uuid
from datetime import datetime
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.models.tool_spec import ApiToolSpec
from app.schemas.decide import DecideRequest, DecideResponse
from app.services.bootstrap_rules import extract_capabilities, BOOTSTRAP_VERSION
from app.core.logger import get_logger

logger = get_logger("decision_engine")


@dataclass
class ScoredTool:
    tool: ApiToolSpec
    score: float
    matched_capabilities: list[str]


def _compute_score(
    tool: ApiToolSpec, 
    target_capabilities: list[str], 
    success_rate: float = 0.5,
    feedback_count: int = 0
) -> float:
    """
    Compute score using v0 formula with dynamic bootstrap decay and low-match protection.
    
    Low-match protection: If no capability matches, success_rate is heavily penalized
    to prevent historical success from overriding capability mismatch.
    """
    # Capability match (1.0 if any capability matches, 0.0 otherwise)
    tool_caps = _parse_tool_capabilities(tool.capabilities)
    capability_match = 1.0 if any(_capability_matches(cap, tool_caps) for cap in target_capabilities) else 0.0
    
    # Convert all numeric inputs to float for type-safe arithmetic
    effective_success_rate = float(success_rate) if success_rate is not None else 0.5
    
    # Bootstrap weight (default 0.5 if not set, convert Decimal to float)
    bootstrap_weight = getattr(tool, 'bootstrap_weight', 0.5)
    effective_bootstrap_weight = float(bootstrap_weight) if bootstrap_weight is not None else 0.5
    
    # Apply dynamic bootstrap decay based on feedback count
    effective_bootstrap_weight = _compute_effective_bootstrap_weight(effective_bootstrap_weight, feedback_count)
    
    # Low-match protection: penalize success_rate when no capability matches
    if capability_match == 0.0:
        # When no capability matches, success_rate is heavily penalized
        # This prevents tools with high historical success from being selected for unrelated tasks
        effective_success_rate = effective_success_rate * 0.1  # 90% penalty
    
    # Apply v0 scoring formula with type-safe float operations
    score = (
        capability_match * 0.70 +
        effective_success_rate * 0.20 +
        effective_bootstrap_weight * 0.10
    )
    
    return round(score, 4)


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
        print(f"Warning: Failed to get feedback count for tool {tool_key}: {e}")
        return 0


def _get_tool_success_rate(db: Session, tool_key: str) -> float:
    """
    Get success rate for a tool from tool_stats table in Supabase.
    
    Args:
        db: SQLAlchemy session connected to Supabase PostgreSQL
        tool_key: The tool identifier
        
    Returns:
        float: Success rate from tool_stats, or 0.5 if not found
    """
    try:
        # Query tool_stats table in Supabase PostgreSQL
        result = db.execute(
            text("""
                SELECT success_rate 
                FROM tool_stats 
                WHERE tool_key = :tool_key
            """),
            {"tool_key": tool_key}
        ).fetchone()
        
        # If record exists and success_rate is not null, return it
        if result and result[0] is not None:
            return float(result[0])
        
        # Default success rate if no record found or success_rate is null
        return 0.5
        
    except Exception as e:
        # Log the error for debugging, but return default success rate
        print(f"Warning: Failed to get success rate for tool {tool_key}: {e}")
        return 0.5  # Fallback to default success rate


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
    
    # Score all tools
    scored_tools = []
    for tool in tools:
        success_rate = _get_tool_success_rate(db, tool.tool_key)
        feedback_count = _get_feedback_count(db, tool.tool_key)
        score = _compute_score(tool, target_capabilities, success_rate, feedback_count)
        
        # Check capability match for explanation
        tool_caps = _parse_tool_capabilities(tool.capabilities)
        matched_caps = [cap for cap in target_capabilities if _capability_matches(cap, tool_caps)]
        
        scored_tools.append(ScoredTool(
            tool=tool,
            score=score,
            matched_capabilities=matched_caps
        ))
    
    # Sort by score descending
    scored_tools.sort(key=lambda x: x.score, reverse=True)
    
    if not scored_tools:
        raise ValueError("No tools matched the task requirements")
    
    # Select top tool
    top_tool = scored_tools[0]
    
    # Log scoring details
    logger.info(f'top tool: {top_tool.tool.tool_key} score={top_tool.score:.4f} feedback_count={_get_feedback_count(db, top_tool.tool.tool_key)}')
    
    # Generate decision ID
    decision_id = f"dec_{uuid.uuid4().hex[:16]}"
    
    # Build explanation
    reason = _build_reason(top_tool, target_capabilities, _get_feedback_count(db, top_tool.tool.tool_key))
    
    # Build explain and trace payloads
    explain = _build_explain_payload(top_tool, target_capabilities, scored_tools)
    trace = _build_trace_payload(request, top_tool, scored_tools, started_at)
    
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


def _build_reason(top_tool: ScoredTool, target_capabilities: list[str], feedback_count: int = 0) -> str:
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
    
    parts.append(f"Execution success rate: {_get_success_rate_display(top_tool.tool)}")
    parts.append(f"Confidence score: {top_tool.score:.2f}")
    
    return "; ".join(parts)


def _get_success_rate_display(tool: ApiToolSpec) -> str:
    """
    Get success rate display string by querying tool_stats table.
    
    Args:
        tool: ApiToolSpec object
        
    Returns:
        str: Formatted success rate string
    """
    # Since success_rate is not stored in ApiToolSpec, we need to query it
    # This is a simplified version - in production, you might want to cache this
    try:
        # Import here to avoid circular imports
        from app.core.database import SessionLocal
        
        with SessionLocal() as db:
            result = db.execute(
                text("SELECT success_rate FROM tool_stats WHERE tool_key = :tool_key"),
                {"tool_key": tool.tool_key}
            ).fetchone()
            
            if result and result[0] is not None:
                return f"{float(result[0]):.0%}"
    except Exception:
        pass  # Fall through to default
    
    return "50% (default)"


def _build_explain_payload(top_tool: ScoredTool, target_capabilities: list[str], all_tools: list[ScoredTool]) -> dict:
    """Build explain payload for auditability."""
    feedback_count = 0
    try:
        from app.core.database import SessionLocal
        with SessionLocal() as db:
            feedback_count = _get_feedback_count(db, top_tool.tool.tool_key)
    except Exception:
        pass
    
    bootstrap_weight = float(getattr(top_tool.tool, 'bootstrap_weight', 0.5) or 0.5)
    effective_bootstrap = _compute_effective_bootstrap_weight(bootstrap_weight, feedback_count)
    
    return {
        "scoring_formula": "capability_match * 0.70 + execution_success_rate * 0.20 + effective_bootstrap_weight * 0.10",
        "selected_capability": {
            "capability_id": top_tool.matched_capabilities[0] if top_tool.matched_capabilities else "general_capability",
            "provider": top_tool.tool.tool_key,
            "score": top_tool.score,
            "matched_capabilities": top_tool.matched_capabilities
        },
        "candidate_count": len(all_tools),
        "feedback_count": feedback_count,
        "effective_bootstrap_weight": effective_bootstrap
    }


def _build_trace_payload(request: DecideRequest, top_tool: ScoredTool, all_tools: list[ScoredTool], started_at: float) -> dict:
    """Build trace payload for debugging."""
    latency_ms = int((time.perf_counter() - started_at) * 1000)
    
    return {
        "timestamp": time.time(),
        "latency_ms": latency_ms,
        "top_candidates": [
            {
                "capability_id": tool.matched_capabilities[0] if tool.matched_capabilities else "general_capability",
                "provider": tool.tool.tool_key,
                "score": tool.score,
                "rank": i + 1
            }
            for i, tool in enumerate(all_tools[:5])
        ]
    }


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
        db.rollback()
        # Log error but don't fail the request
        print(f"Failed to create decision log: {e}")
