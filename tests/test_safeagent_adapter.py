"""Unit tests for WisePick → SafeAgent adapter (deterministic request_id)."""

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from adapters.safeagent_adapter import (  # noqa: E402
    SafeAgentAdapter,
    StubSafeAgentRuntime,
    wisepick_to_safeagent_request_id,
)


class FakeWisePick:
    def __init__(self, ecu: dict) -> None:
        self._ecu = ecu
        self.feedback_calls: list[dict] = []

    def decide(self, task: str) -> dict:
        return dict(self._ecu)

    def feedback(self, decision_id: str, success: bool, latency_ms: int, **kwargs) -> dict:
        self.feedback_calls.append(
            {"decision_id": decision_id, "success": success, "latency_ms": latency_ms, **kwargs}
        )
        return {"ok": True}


def test_wisepick_to_safeagent_request_id_deterministic():
    kwargs = {
        "session_id": "sess-abc",
        "turn_id": 3,
        "task": "Summarize the quarterly report",
        "capability_id": "general_content",
        "provider": "chatgpt",
        "constraints": {"max_cost": 1.0},
    }
    first = wisepick_to_safeagent_request_id(**kwargs)
    second = wisepick_to_safeagent_request_id(**kwargs)
    assert first == second
    assert len(first) == 36  # UUID string


def test_wisepick_to_safeagent_request_id_changes_with_turn():
    base = {
        "session_id": "sess-abc",
        "task": "Summarize the quarterly report",
        "capability_id": "general_content",
        "provider": "chatgpt",
    }
    a = wisepick_to_safeagent_request_id(turn_id=1, **base)
    b = wisepick_to_safeagent_request_id(turn_id=2, **base)
    assert a != b


def test_wisepick_to_safeagent_request_id_ignores_decision_id_not_in_preimage():
    """Same session/turn/task/capability → same request_id regardless of ECU decision_id."""
    ecu_a = {
        "decision_id": "dec_first",
        "capability_id": "search_files",
        "provider": "github_copilot",
        "callable": True,
        "confidence": 0.8,
        "reason": "match",
        "execution_type": "api",
    }
    ecu_b = {**ecu_a, "decision_id": "dec_second", "confidence": 0.9}
    adapter = SafeAgentAdapter(wisepick=FakeWisePick(ecu_a), runtime=StubSafeAgentRuntime())  # type: ignore[arg-type]
    req_a = adapter.ecu_to_dispatch_request(
        ecu_a, task="find TODOs", session_id="s1", turn_id=1
    )
    req_b = adapter.ecu_to_dispatch_request(
        ecu_b, task="find TODOs", session_id="s1", turn_id=1
    )
    assert req_a["request_id"] == req_b["request_id"]
    assert req_a["decision_id"] != req_b["decision_id"]


def test_ecu_to_dispatch_request_includes_deterministic_request_id():
    ecu = {
        "decision_id": "dec_xyz",
        "capability_id": "audio_transcription",
        "provider": "feishu_minutes",
        "execution_type": "api",
        "callable": True,
        "confidence": 0.91,
        "reason": "capability_match",
    }
    adapter = SafeAgentAdapter(
        wisepick=FakeWisePick(ecu),  # type: ignore[arg-type]
        runtime=StubSafeAgentRuntime(),
    )
    dispatch = adapter.ecu_to_dispatch_request(
        ecu,
        task="Transcribe meeting",
        session_id="session-1",
        turn_id="turn-0",
    )
    expected_id = wisepick_to_safeagent_request_id(
        session_id="session-1",
        turn_id="turn-0",
        task="Transcribe meeting",
        capability_id="audio_transcription",
        provider="feishu_minutes",
    )
    assert dispatch["request_id"] == expected_id
    assert dispatch["decision_id"] == "dec_xyz"
    assert dispatch["capability_id"] == "audio_transcription"
    assert dispatch["provider"] == "feishu_minutes"
    assert dispatch["callable"] is True


def test_select_and_execute_passes_request_id_to_runtime():
    ecu = {
        "decision_id": "dec_run",
        "capability_id": "general_content",
        "provider": "chatgpt",
        "execution_type": "api",
        "callable": True,
        "confidence": 0.75,
        "reason": "general",
    }
    runtime = StubSafeAgentRuntime()
    wp = FakeWisePick(ecu)
    adapter = SafeAgentAdapter(wisepick=wp, runtime=runtime)  # type: ignore[arg-type]

    out = adapter.select_and_execute(
        "Write a one-line summary",
        session_id="sess-99",
        turn_id=7,
    )

    assert out["request_id"]
    assert len(runtime.calls) == 1
    assert runtime.calls[0]["request_id"] == out["request_id"]
    assert runtime.calls[0]["decision_id"] == "dec_run"
    assert len(wp.feedback_calls) == 1
    assert wp.feedback_calls[0]["decision_id"] == "dec_run"
    assert wp.feedback_calls[0]["success"] is True


def test_select_and_execute_non_callable_skips_runtime():
    ecu = {
        "decision_id": "dec_nc",
        "capability_id": "none",
        "provider": "none",
        "callable": False,
        "confidence": 0.0,
        "reason": "no match",
        "execution_type": "api",
    }
    runtime = StubSafeAgentRuntime()
    wp = FakeWisePick(ecu)
    adapter = SafeAgentAdapter(wisepick=wp, runtime=runtime)  # type: ignore[arg-type]

    out = adapter.select_and_execute("unknown task", session_id="s", turn_id=1)

    assert runtime.calls == []
    assert out["trace"]["error"] == "ECU callable=false"
    assert len(wp.feedback_calls) == 1
    assert wp.feedback_calls[0]["success"] is False
