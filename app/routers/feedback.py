"""
Feedback router for WisePick API v0.
Records tool execution outcomes to update success metrics.
"""
from datetime import datetime
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.database import get_db
from app.core.logger import get_logger

router = APIRouter(prefix="/v1", tags=["feedback"])
logger = get_logger("feedback")


class FeedbackRequest(BaseModel):
    """Feedback request model."""
    decision_id: str
    success: bool
    latency_ms: int = None
    user_note: str = ""


@router.post("/feedback")
def record_feedback(
    request: FeedbackRequest,
    db: Session = Depends(get_db)
) -> dict:
    """
    Record feedback for a decision.
    
    Args:
        request: Feedback request containing decision_id and success
    
    Returns:
        {"ok": true} if feedback was recorded successfully
    """
    # 记录反馈接收
    logger.info(f'decision_id={request.decision_id} success={request.success}')
    
    # Validate that the decision exists and get the tool_key
    decision = _get_decision(db, request.decision_id)
    if not decision:
        logger.error(f'decision not found: {request.decision_id}')
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "message": "Decision not found"}
        )
    
    tool_key = decision["selected_tool_key"]
    
    # Record feedback
    try:
        _insert_feedback(db, request.decision_id, tool_key, request.success, request.latency_ms, request.user_note)
        
        # 记录反馈成功
        logger.info(f'decision_id={request.decision_id} tool={tool_key} success={request.success}')
        
        return {"ok": True}
    except Exception as e:
        # 记录反馈失败
        logger.error(f'feedback failed: decision_id={request.decision_id} error={str(e)}')
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "message": f"Failed to record feedback: {str(e)}"}
        )


def _get_decision(db: Session, decision_id: str) -> dict:
    """Get decision by ID."""
    result = db.execute(
        text("SELECT selected_tool_key FROM decisions WHERE decision_id = :decision_id"),
        {"decision_id": decision_id}
    ).fetchone()
    
    if result:
        return {"selected_tool_key": result[0]}
    return None


def _insert_feedback(db: Session, decision_id: str, tool_key: str, success: bool, 
                    latency_ms: int, user_note: str) -> None:
    """Insert feedback record."""
    db.execute(
        text("""
            INSERT INTO feedback 
            (decision_id, tool_key, outcome, success, latency_ms, user_note, trace, created_at)
            VALUES 
            (:decision_id, :tool_key, :outcome, :success, :latency_ms, :user_note, :trace, :created_at)
        """),
        {
            "decision_id": decision_id,
            "tool_key": tool_key,
            "outcome": "completed",
            "success": success,
            "latency_ms": latency_ms,
            "user_note": user_note,
            "trace": "{}",
            "created_at": datetime.utcnow()
        }
    )
    db.commit()
