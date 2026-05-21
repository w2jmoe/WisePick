"""Feedback request schema tests."""

import pytest
from pydantic import ValidationError

from app.schemas.feedback import FeedbackRequest, TokenCost


def test_feedback_requires_latency_ms():
    with pytest.raises(ValidationError):
        FeedbackRequest(decision_id="dec_x", success=True)


def test_feedback_accepts_roi_fields():
    req = FeedbackRequest(
        decision_id="dec_x",
        success=True,
        latency_ms=1200,
        token_cost=TokenCost(input=100, output=50),
        result_quality=0.85,
    )
    assert req.token_cost.input == 100
    assert req.result_quality == 0.85


def test_result_quality_bounds():
    with pytest.raises(ValidationError):
        FeedbackRequest(decision_id="dec_x", success=True, latency_ms=1, result_quality=1.5)
