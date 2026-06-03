"""Feedback request schemas for POST /v1/feedback."""

from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.services.feedback_validation import LATENCY_MS_MAX, LATENCY_MS_MIN


class TokenCost(BaseModel):
    """Token usage for ROI aggregation (maps to feedback.token_cost JSON)."""

    input: Optional[int] = Field(default=None, ge=0, description="Input tokens consumed")
    output: Optional[int] = Field(default=None, ge=0, description="Output tokens consumed")

    @field_validator("input", "output", mode="before")
    @classmethod
    def _empty_to_none(cls, v: object) -> Optional[int]:
        if v is None or v == "":
            return None
        return int(v)  # type: ignore[arg-type]


class FeedbackRequest(BaseModel):
    """Multi-dimensional execution feedback for ROI learning."""

    decision_id: str = Field(..., min_length=1)
    success: bool
    latency_ms: int = Field(
        ...,
        ge=LATENCY_MS_MIN,
        le=LATENCY_MS_MAX,
        description="Wall-clock execution duration in milliseconds (1–86400000)",
    )
    tool_key: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Optional; when sent must match the decision selected_tool_key",
    )
    token_cost: Optional[TokenCost] = Field(default=None, description="Optional input/output token counts")
    result_quality: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Optional execution quality score (0.0–1.0)",
    )
    user_note: str = Field(default="", description="Optional free-text note (errors, context)")
    runtime_name: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Optional runtime self-label for usage analytics only",
    )

    @field_validator("runtime_name", mode="before")
    @classmethod
    def _normalize_runtime_name(cls, v: object) -> Optional[str]:
        if v is None or v == "":
            return None
        stripped = str(v).strip()
        return stripped or None
