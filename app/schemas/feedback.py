"""Feedback request schemas for POST /v1/feedback."""

from typing import Optional

from pydantic import BaseModel, Field, field_validator


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
    latency_ms: int = Field(..., ge=0, description="Wall-clock execution duration in milliseconds")
    token_cost: Optional[TokenCost] = Field(default=None, description="Optional input/output token counts")
    result_quality: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Optional execution quality score (0.0–1.0)",
    )
    user_note: str = Field(default="", description="Optional free-text note (errors, context)")
