"""
Read-only usage analytics aggregated from decisions, feedback, and tool_stats.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import rollback_session
from app.core.logger import get_logger
from app.schemas.analytics import (
    AnalyticsDashboardResponse,
    AnalyticsSummaryResponse,
    AnalyticsTimelineResponse,
    ProviderStatsResponse,
    TimelineDayResponse,
)

logger = get_logger("analytics_service")


def _scalar_int(row: Any, default: int = 0) -> int:
    if row is None or row[0] is None:
        return default
    return int(row[0])


def _scalar_float(row: Any) -> Optional[float]:
    if row is None or row[0] is None:
        return None
    return round(float(row[0]), 4)


def get_analytics_summary(db: Session) -> AnalyticsSummaryResponse:
    """Aggregate global usage and ROI metrics."""
    try:
        decisions_total = _scalar_int(
            db.execute(text("SELECT COUNT(*) FROM decisions")).fetchone()
        )
        feedback_total = _scalar_int(
            db.execute(text("SELECT COUNT(*) FROM feedback")).fetchone()
        )
        closure_rate = round(feedback_total / decisions_total, 4) if decisions_total else 0.0

        active_providers = _scalar_int(
            db.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM tool_stats
                    WHERE COALESCE(decision_count, 0) > 0
                    """
                )
            ).fetchone()
        )

        roi_row = db.execute(
            text(
                """
                SELECT
                    AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END),
                    AVG(latency_ms),
                    AVG(
                        COALESCE((token_cost->>'input')::numeric, 0)
                      + COALESCE((token_cost->>'output')::numeric, 0)
                    ) FILTER (WHERE token_cost IS NOT NULL),
                    AVG(result_quality) FILTER (WHERE result_quality IS NOT NULL)
                FROM feedback
                """
            )
        ).fetchone()

        avg_success_rate = _scalar_float((roi_row[0],)) if roi_row else None
        avg_latency_ms = (
            round(float(roi_row[1]), 2) if roi_row and roi_row[1] is not None else None
        )
        avg_token_cost = (
            round(float(roi_row[2]), 2) if roi_row and roi_row[2] is not None else None
        )
        avg_result_quality = _scalar_float((roi_row[3],)) if roi_row else None

        top_row = db.execute(
            text(
                """
                SELECT tool_key, decision_count, feedback_count
                FROM tool_stats
                WHERE COALESCE(decision_count, 0) > 0
                ORDER BY decision_count DESC, tool_key ASC
                LIMIT 1
                """
            )
        ).fetchone()

        top_provider = None
        top_provider_decisions = 0
        top_provider_feedback_count = 0
        if top_row:
            top_provider = str(top_row[0])
            top_provider_decisions = int(top_row[1] or 0)
            top_provider_feedback_count = int(top_row[2] or 0)

        return AnalyticsSummaryResponse(
            decisions_total=decisions_total,
            feedback_total=feedback_total,
            closure_rate=closure_rate,
            active_providers=active_providers,
            avg_success_rate=avg_success_rate,
            avg_latency_ms=avg_latency_ms,
            avg_token_cost=avg_token_cost,
            avg_result_quality=avg_result_quality,
            top_provider=top_provider,
            top_provider_decisions=top_provider_decisions,
            top_provider_feedback_count=top_provider_feedback_count,
        )
    except Exception as exc:
        rollback_session(db)
        logger.error("analytics summary failed: %s", exc)
        raise


def _count_since_days(db: Session, table: str, days: int) -> int:
    if table not in {"decisions", "feedback"}:
        raise ValueError(f"unsupported analytics table: {table}")
    return _scalar_int(
        db.execute(
            text(
                f"""
                SELECT COUNT(*)
                FROM {table}
                WHERE created_at >= NOW() - make_interval(days => :days)
                """
            ),
            {"days": days},
        ).fetchone()
    )


def get_analytics_dashboard(db: Session) -> AnalyticsDashboardResponse:
    """Operator dashboard: summary metrics plus recent 7-day volume."""
    try:
        summary = get_analytics_summary(db)
        return AnalyticsDashboardResponse(
            **summary.model_dump(),
            decisions_last_7d=_count_since_days(db, "decisions", 7),
            feedback_last_7d=_count_since_days(db, "feedback", 7),
        )
    except Exception as exc:
        rollback_session(db)
        logger.error("analytics dashboard failed: %s", exc)
        raise


def get_provider_stats(db: Session) -> list[ProviderStatsResponse]:
    """Return per-provider aggregates from tool_stats."""
    try:
        rows = db.execute(
            text(
                """
                SELECT
                    tool_key,
                    name,
                    COALESCE(decision_count, 0),
                    COALESCE(feedback_count, 0),
                    success_rate,
                    avg_latency_ms,
                    avg_token_cost,
                    avg_result_quality,
                    last_feedback_at
                FROM tool_stats
                ORDER BY decision_count DESC NULLS LAST, tool_key ASC
                """
            )
        ).fetchall()

        return [
            ProviderStatsResponse(
                tool_key=str(row[0]),
                name=str(row[1] or row[0]),
                decision_count=int(row[2] or 0),
                feedback_count=int(row[3] or 0),
                success_rate=_scalar_float((row[4],)),
                avg_latency_ms=(
                    round(float(row[5]), 2) if row[5] is not None else None
                ),
                avg_token_cost=(
                    round(float(row[6]), 2) if row[6] is not None else None
                ),
                avg_result_quality=_scalar_float((row[7],)),
                last_feedback_at=row[8],
            )
            for row in rows
        ]
    except Exception as exc:
        rollback_session(db)
        logger.error("analytics providers failed: %s", exc)
        raise


def get_analytics_timeline(db: Session) -> AnalyticsTimelineResponse:
    """Daily decision and feedback counts grouped by UTC day."""
    try:
        decision_rows = db.execute(
            text(
                """
                SELECT (created_at AT TIME ZONE 'UTC')::date AS day, COUNT(*)
                FROM decisions
                GROUP BY 1
                ORDER BY 1
                """
            )
        ).fetchall()
        feedback_rows = db.execute(
            text(
                """
                SELECT (created_at AT TIME ZONE 'UTC')::date AS day, COUNT(*)
                FROM feedback
                GROUP BY 1
                ORDER BY 1
                """
            )
        ).fetchall()

        by_day: dict[date, dict[str, int]] = {}
        for day_value, count in decision_rows:
            day_key = day_value if isinstance(day_value, date) else day_value.date()
            bucket = by_day.setdefault(day_key, {"decisions": 0, "feedback": 0})
            bucket["decisions"] = int(count)

        for day_value, count in feedback_rows:
            day_key = day_value if isinstance(day_value, date) else day_value.date()
            bucket = by_day.setdefault(day_key, {"decisions": 0, "feedback": 0})
            bucket["feedback"] = int(count)

        days = [
            TimelineDayResponse(
                date=day_key,
                decisions=counts["decisions"],
                feedback=counts["feedback"],
            )
            for day_key, counts in sorted(by_day.items())
        ]
        return AnalyticsTimelineResponse(days=days)
    except Exception as exc:
        rollback_session(db)
        logger.error("analytics timeline failed: %s", exc)
        raise
