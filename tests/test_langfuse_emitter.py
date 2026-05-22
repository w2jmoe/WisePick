"""Langfuse routing telemetry (mcp.route_decision.v1)."""

from unittest.mock import MagicMock, patch

import pytest

from app.schemas.decide import DecideRequest, DecideResponse
from app.telemetry.langfuse_emitter import (
    EXECUTION_FEEDBACK_SCHEMA,
    LangfuseEmitter,
    build_execution_feedback_payload,
    build_route_decision_payload,
    emit_route_decision_async,
    get_langfuse_emitter,
)


def _sample_response(*, confidence: float = 0.91) -> DecideResponse:
    return DecideResponse(
        decision_id="dec_test123",
        capability_id="json_document_migration",
        execution_type="api",
        provider="couchdb_replicator",
        callable=True,
        tool_key="couchdb_replicator",
        reason="matched",
        confidence=confidence,
        explain={
            "candidate_count": 3,
            "feedback_count": 0,
            "selected_capability": {
                "score": 0.91,
                "matched_capabilities": ["json_document_migration"],
            },
        },
        trace={
            "latency_ms": 2,
            "top_candidates": [
                {
                    "rank": 1,
                    "provider": "couchdb_replicator",
                    "capability_id": "json_document_migration",
                    "score": 0.91,
                },
                {
                    "rank": 2,
                    "provider": "other_tool",
                    "capability_id": "other_cap",
                    "score": 0.40,
                },
            ],
        },
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

    meta = payload["metadata"]
    assert meta["schema_version"] == "mcp.route_decision.v1"
    assert meta["wisepick_decision_id"] == "dec_test123"
    assert meta["upstream_trace_id"] == "trace-abc"
    assert meta["session_id"] == "sess-xyz"
    assert len(meta["decision_id"]) == 32
    assert len(meta["trace_id"]) == 32
    assert payload["decision_id"] == meta["decision_id"]
    assert payload["trace_id"] == meta["trace_id"]
    assert meta["capability_id"] == "json_document_migration"
    assert meta["provider"] == "couchdb_replicator"
    assert meta["callable"] is True
    assert meta["confidence"] == 0.91
    assert meta["latency_ms"] == 2
    assert meta["candidate_count"] == 3
    assert meta["reason_codes"] == ["capability_match"]
    assert len(meta["top_candidates"]) == 2
    assert meta["top_candidates"][0]["selected"] is True
    assert meta["top_candidates"][0]["tool_key"] == "couchdb_replicator"
    assert "arguments" not in payload
    assert "task" not in str(payload)
    assert "api_key" not in str(payload)


def test_build_route_decision_low_confidence_blocks_callable():
    payload = build_route_decision_payload(
        DecideRequest(task="x"),
        _sample_response(confidence=0.005),
    )
    meta = payload["metadata"]
    assert meta["callable"] is False
    assert meta["capability_id"] == "none"
    assert meta["provider"] == "none"
    assert meta["top_candidates"] == []
    assert meta["reason_codes"] == ["no_match_found"]


def test_build_execution_feedback_payload_links_trace():
    payload = build_execution_feedback_payload(
        decision_id="dec_test123",
        tool_key="feishu_minutes",
        success=True,
        latency_ms=1200,
        token_cost={"input": 100, "output": 50},
        result_quality=0.9,
        decision_context={"trace_id": "trace-abc", "session_id": "sess-1"},
    )
    assert payload["metadata"]["schema_version"] == EXECUTION_FEEDBACK_SCHEMA
    assert payload["trace_id"] == "trace-abc"
    assert payload["parent_span_id"] == "dec_test123:route"
    assert payload["output"]["latency_ms"] == 1200
    assert payload["output"]["token_cost"]["input"] == 100
    assert payload["output"]["result_quality"] == 0.9


def test_emitter_disabled_without_keys():
    emitter = LangfuseEmitter(public_key="", secret_key="")
    assert emitter.enabled is False
    emitter.emit_route_decision(
        DecideRequest(task="x"),
        _sample_response(),
    )


@patch("app.telemetry.langfuse_emitter.urllib.request.urlopen")
def test_ingestion_batch_posts_contract(mock_urlopen: MagicMock):
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = b'{"success":true}'
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
def test_post_json_logs_non_200(mock_urlopen: MagicMock):
    mock_resp = MagicMock()
    mock_resp.status = 207
    mock_resp.read.return_value = b'{"errors":[{"id":"dup"}]}'
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_resp

    emitter = LangfuseEmitter(public_key="pk", secret_key="sk", host="https://langfuse.example")
    status = emitter._post_json("https://langfuse.example/api/public/ingestion", {"batch": []})
    assert status == 207


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
