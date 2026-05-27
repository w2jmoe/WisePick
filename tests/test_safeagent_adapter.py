"""Unit tests for WisePick → SafeAgent adapter (deterministic request_id + start_time_ms)."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from adapters.safeagent_adapter import (  # noqa: E402
    SafeAgentAdapter,
    StubSafeAgentRuntime,
    wisepick_to_safeagent_request_id,
)

# Fixed orchestrator turn anchor (epoch ms) — must not depend on local clock in tests.
FIXED_START_TIME_MS = 1716780000000.0


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


def _id_kwargs(**extra: object) -> dict:
    base = {
        "session_id": "sess-abc",
        "turn_id": 3,
        "task": "Summarize the quarterly report",
        "capability_id": "general_content",
        "provider": "chatgpt",
        "start_time_ms": FIXED_START_TIME_MS,
        "constraints": {"max_cost": 1.0},
    }
    base.update(extra)
    return base


def test_wisepick_to_safeagent_request_id_deterministic_with_fixed_start_time():
    first = wisepick_to_safeagent_request_id(**_id_kwargs())
    second = wisepick_to_safeagent_request_id(**_id_kwargs())
    assert first == second
    assert len(first) == 36


def test_wisepick_to_safeagent_request_id_stable_ignores_local_clock():
    """Same fixed start_time → same request_id even if default clock would differ."""
    with patch("adapters.safeagent_adapter.time.time", return_value=9999999999.0):
        a = wisepick_to_safeagent_request_id(**_id_kwargs())
    with patch("adapters.safeagent_adapter.time.time", return_value=1.0):
        b = wisepick_to_safeagent_request_id(**_id_kwargs())
    assert a == b


def test_wisepick_to_safeagent_request_id_changes_with_turn():
    a = wisepick_to_safeagent_request_id(**_id_kwargs(turn_id=1))
    b = wisepick_to_safeagent_request_id(**_id_kwargs(turn_id=2))
    assert a != b


def test_wisepick_to_safeagent_request_id_changes_with_start_time():
    a = wisepick_to_safeagent_request_id(**_id_kwargs(start_time_ms=FIXED_START_TIME_MS))
    b = wisepick_to_safeagent_request_id(**_id_kwargs(start_time_ms=FIXED_START_TIME_MS + 1))
    assert a != b


def test_wisepick_to_safeagent_request_id_ignores_decision_id_not_in_preimage():
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
        ecu_a,
        task="find TODOs",
        session_id="s1",
        turn_id=1,
        start_time=FIXED_START_TIME_MS,
    )
    req_b = adapter.ecu_to_dispatch_request(
        ecu_b,
        task="find TODOs",
        session_id="s1",
        turn_id=1,
        start_time=FIXED_START_TIME_MS,
    )
    assert req_a["request_id"] == req_b["request_id"]
    assert req_a["decision_id"] != req_b["decision_id"]
    assert req_a["startTime_ms"] == int(FIXED_START_TIME_MS)


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
        start_time=FIXED_START_TIME_MS,
    )
    expected_id = wisepick_to_safeagent_request_id(
        session_id="session-1",
        turn_id="turn-0",
        task="Transcribe meeting",
        capability_id="audio_transcription",
        provider="feishu_minutes",
        start_time_ms=FIXED_START_TIME_MS,
    )
    assert dispatch["request_id"] == expected_id
    assert dispatch["startTime_ms"] == int(FIXED_START_TIME_MS)
    assert dispatch["decision_id"] == "dec_xyz"


def test_select_and_execute_passes_request_id_and_start_time_to_runtime():
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
        start_time=FIXED_START_TIME_MS,
    )

    assert out["request_id"]
    assert len(runtime.calls) == 1
    assert runtime.calls[0]["request_id"] == out["request_id"]
    assert runtime.calls[0]["startTime_ms"] == int(FIXED_START_TIME_MS)
    assert runtime.calls[0]["decision_id"] == "dec_run"
    assert len(wp.feedback_calls) == 1


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

    out = adapter.select_and_execute(
        "unknown task",
        session_id="s",
        turn_id=1,
        start_time=FIXED_START_TIME_MS,
    )

    assert runtime.calls == []
    assert out["trace"]["error"] == "ECU callable=false"
