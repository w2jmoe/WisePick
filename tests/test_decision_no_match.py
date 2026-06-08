"""Decision engine no-match routing (callable=false)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.tool_spec import ApiToolSpec
from app.schemas.decide import DecideRequest
from app.services.decision_engine import (
    FALLBACK_UNKNOWN_TOOL_KEY,
    NO_MATCH_REASON,
    _should_reject_no_match,
    run_decision,
)
from app.services.decision_engine import ScoredTool, _compute_score


def _make_tool(
    tool_key: str,
    capabilities: str,
    bootstrap_weight: float = 0.5,
) -> ApiToolSpec:
    tool = ApiToolSpec(
        tool_key=tool_key,
        name=tool_key,
        description="",
        capabilities=capabilities,
        enabled=True,
        bootstrap_weight=Decimal(str(bootstrap_weight)),
        meta={},
    )
    return tool


def test_should_reject_when_target_capabilities_empty() -> None:
    tool = _make_tool("feishu_minutes", "transcription,audio,meeting", 0.7)
    bd = _compute_score(tool, [], {})
    scored = [
        ScoredTool(
            tool=tool,
            score=bd["final_score"],
            matched_capabilities=[],
            base_score=bd["base_score"],
            efficacy=bd["efficacy"],
            metrics={},
            score_breakdown=bd,
        )
    ]
    assert _should_reject_no_match([], scored) is True


def test_should_not_reject_when_capability_matches() -> None:
    tool = _make_tool("chatgpt", "writing,general_content", 0.6)
    targets = ["writing"]
    bd = _compute_score(tool, targets, {})
    scored = [
        ScoredTool(
            tool=tool,
            score=bd["final_score"],
            matched_capabilities=["writing"],
            base_score=bd["base_score"],
            efficacy=bd["efficacy"],
            metrics={},
            score_breakdown=bd,
        )
    ]
    assert _should_reject_no_match(targets, scored) is False


def test_run_decision_no_match_persists_fallback_unknown() -> None:
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        _make_tool("feishu_minutes", "transcription,audio,meeting", 0.7),
        _make_tool("chatgpt", "writing,general_content", 0.6),
    ]
    insert_params: dict = {}

    def _execute(stmt, params=None):
        result = MagicMock()
        sql = str(stmt)
        if "tool_stats" in sql:
            result.fetchone.return_value = None
        elif "INSERT INTO decisions" in sql:
            insert_params.update(params or {})
            result.fetchone.return_value = None
        else:
            result.fetchone.return_value = None
        return result

    db.execute.side_effect = _execute

    out = run_decision(
        DecideRequest(task="帮我查询今天东京天气"),
        db,
    )

    assert out.callable is False
    assert out.provider == ""
    assert out.tool_key == ""
    assert out.capability_id == ""
    assert out.reason == NO_MATCH_REASON
    assert out.confidence == 0.0
    assert out.explain.get("no_match") is True
    assert out.decision_id.startswith("dec_")
    assert insert_params.get("selected_tool_key") == FALLBACK_UNKNOWN_TOOL_KEY
    assert insert_params.get("decision_id") == out.decision_id
    assert insert_params.get("confidence") == 0.0
    assert insert_params.get("reason") == NO_MATCH_REASON


def test_run_decision_matched_task_still_routes() -> None:
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        _make_tool("feishu_minutes", "transcription,audio,meeting", 0.7),
        _make_tool("chatgpt", "writing,general_content", 0.6),
    ]
    insert_called = False

    def _execute(stmt, params=None):
        nonlocal insert_called
        result = MagicMock()
        sql = str(stmt)
        if "tool_stats" in sql:
            result.fetchone.return_value = None
        elif "INSERT INTO decisions" in sql:
            insert_called = True
            assert (params or {}).get("selected_tool_key") != FALLBACK_UNKNOWN_TOOL_KEY
            result.fetchone.return_value = None
        else:
            result.fetchone.return_value = None
        return result

    db.execute.side_effect = _execute

    out = run_decision(
        DecideRequest(task="帮我写一封邮件总结会议"),
        db,
    )

    assert out.callable is True
    assert out.provider in {"feishu_minutes", "chatgpt"}
    assert insert_called is True


@patch("app.routers.feedback.upsert_observed_tool")
@patch("app.routers.feedback._insert_feedback", return_value=True)
@patch("app.routers.feedback._get_decision")
@patch("app.routers.feedback.emit_execution_feedback_async")
def test_feedback_links_no_match_decision(
    _emit: MagicMock,
    mock_get_decision: MagicMock,
    mock_insert: MagicMock,
    _upsert: MagicMock,
) -> None:
    mock_get_decision.return_value = {
        "selected_tool_key": FALLBACK_UNKNOWN_TOOL_KEY,
        "context": {},
        "task": "帮我查询今天东京天气",
    }
    client = TestClient(app)
    response = client.post(
        "/v1/feedback",
        json={
            "decision_id": "dec_no_match_test",
            "success": True,
            "latency_ms": 900,
            "actual_tool_used": "browser_navigate",
            "runtime_name": "hermes",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert mock_insert.call_args.kwargs["tool_key"] == FALLBACK_UNKNOWN_TOOL_KEY
    _upsert.assert_called_once()
    assert _upsert.call_args.kwargs["tool_key"] == "browser_navigate"
