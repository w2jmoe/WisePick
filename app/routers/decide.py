from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.logger import get_logger
from app.schemas.decide import DecideRequest, DecideResponse
from app.services.decision_engine import run_decision
from app.telemetry.langfuse_emitter import emit_route_decision_async

router = APIRouter(prefix="/v1", tags=["decide"])
logger = get_logger("decide")


@router.post("/decide", response_model=DecideResponse)
def decide(request: DecideRequest, response: Response, db: Session = Depends(get_db)):
    # 记录请求接收
    logger.info(f'task="{request.task[:50]}{"..." if len(request.task) > 50 else ""}"')
    
    try:
        out = run_decision(request, db)
        
        # 记录能力路由完成
        latency_ms = out.trace.get("latency_ms", 0) if hasattr(out, 'trace') else 0
        logger.info(f'routed capability={out.capability_id} provider={out.provider} confidence={out.confidence:.2f} latency={latency_ms}ms')
        
        response.headers["X-Decision-ID"] = out.decision_id
        response.headers["X-Observability-Stored"] = "decisions"
        print(f"[DEBUG] decide: calling emit_route_decision_async decision_id={out.decision_id}")
        emit_route_decision_async(request, out)
        return out
    except ValueError as e:
        # 记录错误
        logger.error(f'decision failed: {str(e)}')
        return JSONResponse(
            status_code=422,
            content={"error": "invalid_request", "message": str(e)}
        )
    except Exception as e:
        logger.error(f'decision persistence failed: {str(e)}')
        return JSONResponse(
            status_code=500,
            content={
                "error": "persistence_failed",
                "message": "Failed to persist decision log",
            },
        )
