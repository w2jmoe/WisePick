"""
Feedback router for WisePick API v0.
Records tool execution outcomes to update success metrics.
"""
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.database import get_db, rollback_session
from app.core.logger import get_logger
from app.schemas.feedback import FeedbackRequest
from app.services.feedback_validation import validate_tool_key_for_decision
from app.services.schema_compat import feedback_has_actual_tool_used, feedback_has_runtime_name
from app.services.observed_tools import upsert_observed_tool
from app.telemetry.langfuse_emitter import emit_execution_feedback_async

router = APIRouter(prefix="/v1", tags=["feedback"])
logger = get_logger("feedback")


@router.post("/feedback")
def record_feedback(
    request: FeedbackRequest,
    db: Session = Depends(get_db),
) -> dict:
    """
    Record feedback for a decision.
    """
    logger.info(
        f"decision_id={request.decision_id} success={request.success} "
        f"latency_ms={request.latency_ms} actual_tool_used={request.actual_tool_used}"
    )

    decision = _get_decision(db, request.decision_id)
    if not decision:
        logger.error(f"decision not found: {request.decision_id}")
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "message": "decision_id not found"},
        )

    selected_tool_key = decision["selected_tool_key"]
    tool_key_error = validate_tool_key_for_decision(
        request.tool_key,
        selected_tool_key,
    )
    if tool_key_error:
        logger.error(
            "tool_key mismatch: decision_id=%s client_tool_key=%s selected=%s",
            request.decision_id,
            request.tool_key,
            selected_tool_key,
        )
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_request", "message": tool_key_error},
        )

    tool_key = selected_tool_key
    token_cost_dict = (
        request.token_cost.model_dump(exclude_none=True) if request.token_cost else None
    )

    try:
        inserted = _insert_feedback(
            db,
            decision_id=request.decision_id,
            tool_key=tool_key,
            success=request.success,
            latency_ms=request.latency_ms,
            token_cost=token_cost_dict,
            result_quality=request.result_quality,
            user_note=request.user_note,
            runtime_name=request.runtime_name,
            actual_tool_used=request.actual_tool_used,
        )
        roi_tool = request.actual_tool_used or tool_key
        logger.info(
            f"decision_id={request.decision_id} recommended={tool_key} "
            f"roi_tool={roi_tool} success={request.success}"
        )
        if inserted:
            emit_execution_feedback_async(
                decision_id=request.decision_id,
                tool_key=tool_key,
                success=request.success,
                latency_ms=request.latency_ms,
                token_cost=token_cost_dict,
                result_quality=request.result_quality,
                decision_context=decision.get("context"),
                actual_tool_used=request.actual_tool_used,
            )
            if request.actual_tool_used:
                upsert_observed_tool(
                    db,
                    tool_key=request.actual_tool_used,
                    success=request.success,
                    latency_ms=request.latency_ms,
                    result_quality=request.result_quality,
                    runtime_name=request.runtime_name,
                    task=decision.get("task"),
                )
        return {"ok": True}
    except Exception as e:
        rollback_session(db)
        logger.error(f"feedback failed: decision_id={request.decision_id} error={str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "message": f"Failed to record feedback: {str(e)}"},
        )


def _get_decision(db: Session, decision_id: str) -> Optional[dict[str, Any]]:
    """Get decision by ID (tool + context for Langfuse correlation)."""
    result = db.execute(
        text(
            "SELECT selected_tool_key, context, task FROM decisions WHERE decision_id = :decision_id"
        ),
        {"decision_id": decision_id},
    ).fetchone()

    if result:
        ctx = result[1]
        if isinstance(ctx, str):
            import json
            try:
                ctx = json.loads(ctx)
            except json.JSONDecodeError:
                ctx = {}
        return {
            "selected_tool_key": result[0],
            "context": ctx if isinstance(ctx, dict) else {},
            "task": result[2] or "",
        }
    return None


def _insert_feedback(
    db: Session,
    *,
    decision_id: str,
    tool_key: str,
    success: bool,
    latency_ms: int,
    token_cost: Optional[dict[str, int]],
    result_quality: Optional[float],
    user_note: str,
    runtime_name: Optional[str] = None,
    actual_tool_used: Optional[str] = None,
) -> bool:
    """Insert feedback record with ROI fields. Returns True if a new row was inserted."""
    import json

    params: dict[str, Any] = {
        "decision_id": decision_id,
        "tool_key": tool_key,
        "outcome": "completed",
        "success": success,
        "latency_ms": latency_ms,
        "token_cost": json.dumps(token_cost) if token_cost else None,
        "result_quality": result_quality,
        "user_note": user_note or "",
        "trace": "{}",
        "created_at": datetime.utcnow(),
    }

    columns = [
        "decision_id",
        "tool_key",
        "outcome",
        "success",
        "latency_ms",
        "token_cost",
        "result_quality",
        "user_note",
    ]
    if feedback_has_runtime_name():
        params["runtime_name"] = runtime_name
        columns.append("runtime_name")
    if feedback_has_actual_tool_used():
        params["actual_tool_used"] = actual_tool_used
        columns.append("actual_tool_used")
    columns.extend(["trace", "created_at"])

    col_list = ", ".join(columns)
    val_list = ", ".join(f":{c}" for c in columns)
    insert_sql = f"""
        INSERT INTO feedback ({col_list})
        VALUES ({val_list})
        ON CONFLICT (decision_id) DO NOTHING
        RETURNING id
    """

    result = db.execute(text(insert_sql), params)
    inserted = result.fetchone() is not None
    db.commit()
    return inserted
