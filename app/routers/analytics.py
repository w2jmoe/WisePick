"""Read-only usage analytics endpoints for operator validation."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.logger import get_logger
from app.schemas.analytics import (
    AnalyticsAttributionResponse,
    AnalyticsDashboardResponse,
    AnalyticsSummaryResponse,
    AnalyticsTimelineResponse,
    ProviderStatsResponse,
    RuntimeStatsResponse,
)
from app.services.analytics_service import (
    get_analytics_dashboard,
    get_analytics_summary,
    get_analytics_timeline,
    get_provider_stats,
    get_runtime_stats,
    get_tool_attribution,
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


@router.get("/dashboard", response_model=AnalyticsDashboardResponse)
def analytics_dashboard(db: Session = Depends(get_db)) -> AnalyticsDashboardResponse:
    """Operator dashboard: summary metrics plus last-7-day volume."""
    try:
        return get_analytics_dashboard(db)
    except Exception as exc:
        logger.error("GET /v1/analytics/dashboard failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "message": "Failed to load analytics dashboard",
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


@router.get("/runtimes", response_model=list[RuntimeStatsResponse])
def analytics_runtimes(db: Session = Depends(get_db)) -> list[RuntimeStatsResponse]:
    """Per-runtime feedback stats from self-reported runtime_name."""
    try:
        return get_runtime_stats(db)
    except Exception as exc:
        logger.error("GET /v1/analytics/runtimes failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "message": "Failed to load runtime analytics",
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


@router.get("/attribution", response_model=AnalyticsAttributionResponse)
def analytics_attribution(db: Session = Depends(get_db)) -> AnalyticsAttributionResponse:
    """Recommended tool vs actual_tool_used feedback breakdown."""
    try:
        return get_tool_attribution(db)
    except Exception as exc:
        logger.error("GET /v1/analytics/attribution failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_error",
                "message": "Failed to load tool attribution analytics",
            },
        )
