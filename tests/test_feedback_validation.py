"""POST /v1/feedback data-quality validation tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.feedback_validation import (
    LATENCY_MS_MAX,
    LATENCY_MS_MIN,
    feedback_validation_message,
    validate_tool_key_for_decision,
)


def _valid_body(**overrides: object) -> dict:
    body = {
        "decision_id": "dec_test123",
        "success": True,
        "latency_ms": 1200,
    }
    body.update(overrides)
    return body


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_validate_tool_key_match_ok() -> None:
    assert validate_tool_key_for_decision(None, "feishu_minutes") is None
    assert validate_tool_key_for_decision("feishu_minutes", "feishu_minutes") is None


def test_validate_tool_key_mismatch() -> None:
    assert (
        validate_tool_key_for_decision("wrong_tool", "feishu_minutes")
        == "tool_key does not match decision"
    )


def test_feedback_validation_message_latency() -> None:
    msg = feedback_validation_message(
        [{"loc": ("body", "latency_ms"), "msg": "Input should be greater than or equal to 1"}]
    )
    assert str(LATENCY_MS_MIN) in msg
    assert str(LATENCY_MS_MAX) in msg


def test_feedback_validation_message_token_cost() -> None:
    msg = feedback_validation_message(
        [{"loc": ("body", "token_cost", "input"), "msg": "Input should be greater than or equal to 0"}]
    )
    assert "token_cost" in msg


@patch("app.routers.feedback._insert_feedback", return_value=True)
@patch("app.routers.feedback._get_decision")
@patch("app.routers.feedback.emit_execution_feedback_async")
def test_successful_feedback(
    _emit: MagicMock,
    mock_get_decision: MagicMock,
    mock_insert: MagicMock,
    client: TestClient,
) -> None:
    mock_get_decision.return_value = {
        "selected_tool_key": "feishu_minutes",
        "context": {},
    }
    response = client.post("/v1/feedback", json=_valid_body())
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    mock_insert.assert_called_once()
    call_kwargs = mock_insert.call_args.kwargs
    assert call_kwargs["tool_key"] == "feishu_minutes"
    assert call_kwargs["latency_ms"] == 1200
    assert call_kwargs["runtime_name"] is None


@patch("app.routers.feedback._insert_feedback", return_value=True)
@patch("app.routers.feedback._get_decision")
@patch("app.routers.feedback.emit_execution_feedback_async")
def test_feedback_with_runtime_name(
    _emit: MagicMock,
    mock_get_decision: MagicMock,
    mock_insert: MagicMock,
    client: TestClient,
) -> None:
    mock_get_decision.return_value = {
        "selected_tool_key": "feishu_minutes",
        "context": {},
    }
    response = client.post(
        "/v1/feedback",
        json=_valid_body(runtime_name="yantrikdb-hermes"),
    )
    assert response.status_code == 200
    assert mock_insert.call_args.kwargs["runtime_name"] == "yantrikdb-hermes"


@patch("app.routers.feedback._insert_feedback", return_value=True)
@patch("app.routers.feedback._get_decision")
@patch("app.routers.feedback.emit_execution_feedback_async")
def test_feedback_without_runtime_name(
    _emit: MagicMock,
    mock_get_decision: MagicMock,
    mock_insert: MagicMock,
    client: TestClient,
) -> None:
    mock_get_decision.return_value = {
        "selected_tool_key": "feishu_minutes",
        "context": {},
    }
    response = client.post("/v1/feedback", json=_valid_body())
    assert response.status_code == 200
    assert mock_insert.call_args.kwargs["runtime_name"] is None


@patch("app.routers.feedback._insert_feedback", return_value=True)
@patch("app.routers.feedback._get_decision")
@patch("app.routers.feedback.emit_execution_feedback_async")
def test_feedback_with_actual_tool_used(
    mock_emit: MagicMock,
    mock_get_decision: MagicMock,
    mock_insert: MagicMock,
    client: TestClient,
) -> None:
    mock_get_decision.return_value = {
        "selected_tool_key": "feishu_minutes",
        "context": {},
    }
    response = client.post(
        "/v1/feedback",
        json=_valid_body(actual_tool_used="browser_navigate"),
    )
    assert response.status_code == 200
    assert mock_insert.call_args.kwargs["actual_tool_used"] == "browser_navigate"
    assert mock_emit.call_args.kwargs["actual_tool_used"] == "browser_navigate"


@patch("app.routers.feedback._get_decision", return_value=None)
def test_decision_id_not_found(mock_get_decision: MagicMock, client: TestClient) -> None:
    response = client.post("/v1/feedback", json=_valid_body(decision_id="dec_missing"))
    assert response.status_code == 404
    assert response.json()["message"] == "decision_id not found"


@patch("app.routers.feedback._get_decision")
def test_tool_key_mismatch(mock_get_decision: MagicMock, client: TestClient) -> None:
    mock_get_decision.return_value = {
        "selected_tool_key": "feishu_minutes",
        "context": {},
    }
    response = client.post(
        "/v1/feedback",
        json=_valid_body(tool_key="chatgpt"),
    )
    assert response.status_code == 400
    assert response.json()["message"] == "tool_key does not match decision"


def test_latency_out_of_range(client: TestClient) -> None:
    too_low = client.post("/v1/feedback", json=_valid_body(latency_ms=0))
    assert too_low.status_code == 400
    assert "latency_ms" in too_low.json()["message"]

    too_high = client.post(
        "/v1/feedback",
        json=_valid_body(latency_ms=LATENCY_MS_MAX + 1),
    )
    assert too_high.status_code == 400
    assert "latency_ms" in too_high.json()["message"]


def test_result_quality_out_of_range(client: TestClient) -> None:
    response = client.post(
        "/v1/feedback",
        json=_valid_body(result_quality=1.5),
    )
    assert response.status_code == 400
    assert "result_quality" in response.json()["message"]


def test_token_cost_negative(client: TestClient) -> None:
    response = client.post(
        "/v1/feedback",
        json=_valid_body(token_cost={"input": -1, "output": 10}),
    )
    assert response.status_code == 400
    assert "token_cost" in response.json()["message"]
