"""Read-only analytics response models for operator usage validation."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class AnalyticsSummaryResponse(BaseModel):
    decisions_total: int = Field(..., description="Total routing decisions recorded")
    feedback_total: int = Field(..., description="Total feedback submissions recorded")
    closure_rate: float = Field(
        ...,
        description="feedback_total / decisions_total (0.0 when no decisions)",
    )
    active_providers: int = Field(
        ...,
        description="Providers with at least one routed decision",
    )
    avg_success_rate: Optional[float] = Field(
        default=None,
        description="Mean success rate across all feedback rows",
    )
    avg_latency_ms: Optional[float] = Field(
        default=None,
        description="Mean execution latency (ms) across all feedback rows",
    )
    avg_token_cost: Optional[float] = Field(
        default=None,
        description="Mean input+output tokens where token_cost was reported",
    )
    avg_result_quality: Optional[float] = Field(
        default=None,
        description="Mean result_quality where reported (0.0–1.0)",
    )
    top_provider: Optional[str] = Field(
        default=None,
        description="Provider (tool_key) with the most routed decisions",
    )
    top_provider_decisions: int = Field(
        default=0,
        description="Decision count for top_provider",
    )
    top_provider_feedback_count: int = Field(
        default=0,
        description="Feedback count for top_provider",
    )


class ProviderStatsResponse(BaseModel):
    tool_key: str
    name: str
    decision_count: int
    feedback_count: int
    success_rate: Optional[float] = None
    avg_latency_ms: Optional[float] = None
    avg_token_cost: Optional[float] = None
    avg_result_quality: Optional[float] = None
    last_feedback_at: Optional[datetime] = None


class TimelineDayResponse(BaseModel):
    date: date
    decisions: int
    feedback: int


class AnalyticsTimelineResponse(BaseModel):
    days: list[TimelineDayResponse]
