"""Unit tests for WisePick → ChainWeaver adapter (FlowExecutor contract)."""

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from examples.chainweaver_adapter import (  # noqa: E402
    FlowRouteMapping,
    StubFlowExecutor,
    StubFlowRegistry,
    UnmappedCapabilityError,
    WisePickChainWeaverAdapter,
    WeaverRouterContract,
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


def test_flow_executor_stub_satisfies_execute_flow_contract():
    executor = StubFlowExecutor()
    result = executor.execute_flow("demo_flow", {"task": "hello", "flow_version": "1.0.0"})
    assert result.flow_name == "demo_flow"
    assert result.success is True
    assert result.trace_id
    assert result.duration_ms >= 0
    assert "input" in result.cost
    assert isinstance(result.execution_log, list)


def test_explicit_mapping_required():
    wp = FakeWisePick(
        {
            "decision_id": "dec_x",
            "capability_id": "unknown_cap",
            "provider": "p",
            "callable": True,
            "confidence": 0.9,
            "reason": "test",
        }
    )
    adapter = WisePickChainWeaverAdapter(
        wisepick=wp,  # type: ignore[arg-type]
        registry=StubFlowRegistry({"mapped_flow"}),
        executor=StubFlowExecutor(),
        capability_to_flow={
            "mapped_cap": FlowRouteMapping(flow_id="mapped_flow", flow_version="2.1.0"),
        },
    )
    out = adapter.select_and_execute("do something")
    assert out["trace"]["error"]
    assert "unknown_cap" in out["trace"]["error"]
    assert len(wp.feedback_calls) == 1
    assert wp.feedback_calls[0]["success"] is False


def test_select_and_execute_maps_contract_and_feedback_trace():
    wp = FakeWisePick(
        {
            "decision_id": "dec_abc",
            "capability_id": "audio_transcription",
            "provider": "feishu_minutes",
            "execution_type": "api",
            "callable": True,
            "confidence": 0.88,
            "reason": "capability_match",
        }
    )
    adapter = WisePickChainWeaverAdapter(
        wisepick=wp,  # type: ignore[arg-type]
        registry=StubFlowRegistry({"transcribe_v2"}),
        executor=StubFlowExecutor(),
        capability_to_flow={
            "audio_transcription": FlowRouteMapping(
                flow_id="transcribe_v2",
                flow_version="2.1.0",
            ),
        },
    )
    out = adapter.select_and_execute("Transcribe meeting")

    contract = out["contract"]
    assert contract == {
        "flow_id": "transcribe_v2",
        "flow_version": "2.1.0",
        "confidence": 0.88,
        "reasoning": "capability_match",
    }
    assert WeaverRouterContract(**contract).flow_version == "2.1.0"

    cw = out["trace"]["chainweaver"]
    assert cw["trace_id"]
    assert cw["duration_ms"] == 12
    assert cw["cost"] == {"input": 10, "output": 5}
    assert len(cw["log"]) == 1

    fb = wp.feedback_calls[0]
    assert fb["success"] is True
    note = json.loads(fb["user_note"])
    assert note["chainweaver"]["trace_id"] == cw["trace_id"]
    assert note["flow_version"] == "2.1.0"


def test_unmapped_capability_raises_from_resolve():
    adapter = WisePickChainWeaverAdapter(
        wisepick=FakeWisePick({}),  # type: ignore[arg-type]
        registry=StubFlowRegistry(set()),
        executor=StubFlowExecutor(),
        capability_to_flow={"a": FlowRouteMapping("f", "1.0")},
    )
    with pytest.raises(UnmappedCapabilityError):
        adapter._resolve_mapping("missing")
