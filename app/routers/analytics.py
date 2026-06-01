"""Read-only usage analytics endpoints for operator validation."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.logger import get_logger
from app.schemas.analytics import (
    AnalyticsSummaryResponse,
    AnalyticsTimelineResponse,
    ProviderStatsResponse,
)
from app.services.analytics_service import (
    get_analytics_summary,
    get_analytics_timeline,
    get_provider_stats,
)

router = APIRouter(prefix="/v1/analytics", tags=["analytics"])
logger = get_logger("analytics")


@router.get("/summary", response_model=AnalyticsSummaryResponse)
def analytics_summary(db: Session = Depends(get_db)) -> AnalyticsSummaryResponse:
    """Global usage, closure rate, and pooled ROI aggregates."""
    try:
        return get_analytics_summary(db)
    except Exception as exc:
        logger.error("GET /v1/analytics/summary failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "message": "Failed to load analytics summary",
            },
        )


@router.get("/providers", response_model=list[ProviderStatsResponse])
def analytics_providers(db: Session = Depends(get_db)) -> list[ProviderStatsResponse]:
    """Per-provider stats from the tool_stats view."""
    try:
        return get_provider_stats(db)
    except Exception as exc:
        logger.error("GET /v1/analytics/providers failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "message": "Failed to load provider analytics",
            },
        )


@router.get("/timeline", response_model=AnalyticsTimelineResponse)
def analytics_timeline(db: Session = Depends(get_db)) -> AnalyticsTimelineResponse:
    """Daily decision and feedback counts (UTC)."""
    try:
        return get_analytics_timeline(db)
    except Exception as exc:
        logger.error("GET /v1/analytics/timeline failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "message": "Failed to load analytics timeline",
            },
        )
