"""Smoke tests: ChainWeaverAdapter wiring (no live WisePick API or ChainWeaver install)."""

from __future__ import annotations

from adapters.chainweaver_adapter import (
    ChainWeaverAdapter,
    FlowRouteMapping,
    RoutingDecision,
    StubFlowExecutor,
    StubFlowRegistry,
)


class _StubWisePick:
    def decide(self, task: str) -> dict:
        return {
            "decision_id": "dec_smoke",
            "capability_id": "general_content",
            "provider": "demo",
            "execution_type": "api",
            "callable": True,
            "confidence": 0.75,
            "reason": "smoke capability_match",
        }

    def feedback(self, decision_id: str, success: bool, latency_ms: int, **kwargs) -> dict:
        return {"ok": True}


def test_chainweaver_adapter_initializes() -> None:
    adapter = ChainWeaverAdapter(
        wisepick=_StubWisePick(),  # type: ignore[arg-type]
        registry=StubFlowRegistry({"general_flow"}),
        executor=StubFlowExecutor(),
        capability_to_flow={
            "general_content": FlowRouteMapping(
                flow_id="general_flow",
                flow_version="1.0.0",
            ),
        },
    )
    assert adapter is not None


def test_route_returns_routing_decision() -> None:
    adapter = ChainWeaverAdapter(
        wisepick=_StubWisePick(),  # type: ignore[arg-type]
        registry=StubFlowRegistry({"general_flow"}),
        executor=StubFlowExecutor(),
        capability_to_flow={
            "general_content": FlowRouteMapping(
                flow_id="general_flow",
                flow_version="1.0.0",
            ),
        },
    )
    decision = adapter.route("Say hello")
    assert isinstance(decision, RoutingDecision)
    assert decision.flow_id == "general_flow"
    assert decision.flow_version == "1.0.0"
    assert decision.confidence_bps == 7500
    assert "capability" in decision.reasoning or decision.reasoning


def test_select_and_execute_returns_routing_decision_in_contract() -> None:
    adapter = ChainWeaverAdapter(
        wisepick=_StubWisePick(),  # type: ignore[arg-type]
        registry=StubFlowRegistry({"general_flow"}),
        executor=StubFlowExecutor(),
        capability_to_flow={
            "general_content": FlowRouteMapping(
                flow_id="general_flow",
                flow_version="1.0.0",
            ),
        },
    )
    out = adapter.select_and_execute("Run smoke flow")
    decision = RoutingDecision(**out["contract"])
    assert decision.flow_id == "general_flow"
    assert out["execution"] is not None
    assert out["execution"]["total_duration_ms"] == 42
    assert out["trace"]["error"] is None
