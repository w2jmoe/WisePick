"""Unit tests for WisePick → ChainWeaver adapter (FlowExecutor contract)."""

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from adapters.chainweaver_adapter import (  # noqa: E402
    FlowRouteMapping,
    StubExecutionResult,
    StubFlowExecutor,
    StubFlowRegistry,
    UnmappedCapabilityError,
    WisePickChainWeaverAdapter,
    WeaverRouterContract,
)

# Deterministic wire fixtures (integer-only in test assertions).
CONFIDENCE_BPS_HIGH = 9000
CONFIDENCE_BPS_TRANSCRIBE = 8800
COST_REPORT_MILLICENTS = {"input": 10, "output": 5, "usd_millicents": 1000}


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
    assert result.total_duration_ms == 42
    assert result.duration_ms == 42
    assert "input" in result.cost_report
    assert result.cost_report["usd_millicents"] == COST_REPORT_MILLICENTS["usd_millicents"]
    assert isinstance(result.execution_log, list)


def test_normalize_execution_includes_total_duration_ms_and_cost_report():
    raw = StubExecutionResult(
        flow_name="demo_flow",
        success=True,
        final_output={"ok": True},
        execution_log=[{"step": 1}],
        trace_id="trace-xyz",
        total_duration_ms=99,
        duration_ms=99,
        cost_report={"input": 3, "output": 7, "usd_millicents": 500},
        started_at="t0",
        ended_at="t1",
        initial_input={"task": "x"},
    )
    normalized = WisePickChainWeaverAdapter._normalize_execution(raw)
    assert normalized["total_duration_ms"] == 99
    assert normalized["cost_report"] == {"input": 3, "output": 7, "usd_millicents": 500}
    assert normalized["trace_id"] == "trace-xyz"
    assert normalized["started_at"] == "t0"
    assert normalized["ended_at"] == "t1"
    assert normalized["initial_input"] == {"task": "x"}


def test_explicit_mapping_required():
    wp = FakeWisePick(
        {
            "decision_id": "dec_x",
            "capability_id": "unknown_cap",
            "provider": "p",
            "callable": True,
            "confidence": CONFIDENCE_BPS_HIGH,
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
            "confidence": CONFIDENCE_BPS_TRANSCRIBE,
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
        "confidence_bps": CONFIDENCE_BPS_TRANSCRIBE,
        "reasoning": "capability_match",
    }
    assert WeaverRouterContract(**contract).flow_version == "2.1.0"

    execution = out["execution"]
    assert execution is not None
    assert execution["total_duration_ms"] == 42
    assert execution["cost_report"] == COST_REPORT_MILLICENTS

    cw = out["trace"]["chainweaver"]
    assert cw["trace_id"]
    assert cw["total_duration_ms"] == 42
    assert cw["cost_report"] == COST_REPORT_MILLICENTS
    assert len(cw["execution_log"]) == 1

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
