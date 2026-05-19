"""Langfuse routing telemetry (mcp.route_decision.v1)."""

from unittest.mock import MagicMock, patch

import pytest

from app.schemas.decide import DecideRequest, DecideResponse
from app.telemetry.langfuse_emitter import (
    LangfuseEmitter,
    build_route_decision_payload,
    emit_route_decision_async,
    get_langfuse_emitter,
)


def _sample_response() -> DecideResponse:
    return DecideResponse(
        decision_id="dec_test123",
        capability_id="json_document_migration",
        execution_type="api",
        provider="couchdb_replicator",
        callable=True,
        tool_key="couchdb_replicator",
        reason="matched",
        confidence=0.91,
        explain={"candidate_count": 3, "feedback_count": 0, "selected_capability": {"score": 0.91}},
        trace={"latency_ms": 2},
    )


def test_build_route_decision_payload_contract():
    request = DecideRequest(
        task="Migrate JSON documents — should NOT appear in telemetry",
        context={
            "trace_id": "trace-abc",
            "session_id": "sess-xyz",
            "api_key": "secret-should-not-leak",
        },
        constraints={"max_cost": 10},
    )
    payload = build_route_decision_payload(request, _sample_response())

    assert payload["metadata"]["schema_version"] == "mcp.route_decision.v1"
    assert payload["decision_id"] == "dec_test123"
    assert payload["trace_id"] == "trace-abc"
    assert payload["session_id"] == "sess-xyz"
    assert payload["capability_id"] == "json_document_migration"
    assert payload["provider"] == "couchdb_replicator"
    assert payload["execution_type"] == "api"
    assert payload["callable"] is True
    assert "task" not in payload
    assert "context" not in payload
    assert "constraints" not in payload
    assert payload["arguments"]["confidence"] == 0.91
    assert payload["arguments"]["latency_ms"] == 2
    assert payload["arguments"]["candidate_count"] == 3
    assert "api_key" not in str(payload)


def test_emitter_disabled_without_keys():
    emitter = LangfuseEmitter(public_key="", secret_key="")
    assert emitter.enabled is False
    emitter.emit_route_decision(
        DecideRequest(task="x"),
        _sample_response(),
    )  # no raise


@patch("app.telemetry.langfuse_emitter.urllib.request.urlopen")
def test_ingestion_batch_posts_contract(mock_urlopen: MagicMock):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_resp

    emitter = LangfuseEmitter(
        public_key="pk",
        secret_key="sk",
        host="https://langfuse.example",
        use_otel=False,
    )
    request = DecideRequest(task="hidden", context={"trace_id": "t1"})
    emitter.emit_route_decision(request, _sample_response())

    mock_urlopen.assert_called_once()
    req = mock_urlopen.call_args[0][0]
    assert req.full_url == "https://langfuse.example/api/public/ingestion"
    body = req.data.decode("utf-8")
    assert "mcp.route_decision.v1" in body
    assert "hidden" not in body
    assert "couchdb_replicator" in body


@patch("app.telemetry.langfuse_emitter.urllib.request.urlopen")
def test_otel_mode_uses_otlp_endpoint(mock_urlopen: MagicMock):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_resp

    emitter = LangfuseEmitter(
        public_key="pk",
        secret_key="sk",
        host="https://langfuse.example",
        use_otel=True,
    )
    emitter.emit_route_decision(DecideRequest(task="secret task"), _sample_response())

    req = mock_urlopen.call_args[0][0]
    assert "/api/public/otel/v1/traces" in req.full_url
    assert "secret task" not in req.data.decode("utf-8")


@patch("app.telemetry.langfuse_emitter._executor")
def test_emit_route_decision_async_noop_when_disabled(mock_executor: MagicMock):
    disabled = LangfuseEmitter(public_key="", secret_key="")
    with patch("app.telemetry.langfuse_emitter.get_langfuse_emitter", return_value=disabled):
        emit_route_decision_async(DecideRequest(task="t"), _sample_response())
    mock_executor.submit.assert_not_called()


@patch("app.telemetry.langfuse_emitter._executor")
def test_emit_route_decision_async_submits_when_enabled(mock_executor: MagicMock):
    emitter = LangfuseEmitter(public_key="pk", secret_key="sk")
    with patch("app.telemetry.langfuse_emitter.get_langfuse_emitter", return_value=emitter):
        emit_route_decision_async(DecideRequest(task="t"), _sample_response())
    mock_executor.submit.assert_called_once()
