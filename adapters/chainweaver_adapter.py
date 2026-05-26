"""
WisePick → ChainWeaver adapter.

Routing: POST /v1/decide (ECU). Execution: FlowExecutor.execute_flow. Feedback: POST /v1/feedback.
Explicit capability → (flow_id, flow_version) mapping only — no implicit fallback.

Aligned with ChainWeaver's ExecutionResult specs (trace_id, total_duration_ms, cost_report).
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Protocol, runtime_checkable

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from wisepick import WisePickClient  # noqa: E402

CHAINWEAVER_TRACE_SCHEMA = "mcp.chainweaver_execution.v1"


@runtime_checkable
class FlowRegistryLike(Protocol):
    def get_flow(self, flow_name: str) -> Any: ...


@runtime_checkable
class FlowExecutorLike(Protocol):
    """ChainWeaver API: execute_flow(flow_name, initial_input) → ExecutionResult."""

    def execute_flow(self, flow_name: str, initial_input: Dict[str, Any]) -> Any: ...


@dataclass(frozen=True)
class FlowRouteMapping:
    """Explicit registry entry: capability_id → ChainWeaver flow identity."""

    flow_id: str
    flow_version: str  # Documented as audit/intent metadata rather than guaranteed targeting.


@dataclass(frozen=True)
class WeaverRouterContract:
    flow_id: str
    flow_version: str
    confidence: float
    reasoning: str


@dataclass
class WeaverExecutionTrace:
    decision_id: str
    capability_id: str
    provider: str
    callable: bool
    contract: WeaverRouterContract
    ecu: Dict[str, Any] = field(default_factory=dict)
    chainweaver: Dict[str, Any] = field(default_factory=dict)
    execution: Optional[Dict[str, Any]] = None
    feedback: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class UnmappedCapabilityError(KeyError):
    """Raised when capability_id is absent from the explicit mapping table."""


class WisePickChainWeaverAdapter:
    def __init__(
        self,
        *,
        wisepick: WisePickClient,
        registry: FlowRegistryLike,
        executor: FlowExecutorLike,
        capability_to_flow: Mapping[str, FlowRouteMapping],
    ) -> None:
        self._wp = wisepick
        self._registry = registry
        self._executor = executor
        if not capability_to_flow:
            raise ValueError("capability_to_flow must be a non-empty explicit mapping")
        self._capability_to_flow = dict(capability_to_flow)

    def _resolve_mapping(self, capability_id: str) -> FlowRouteMapping:
        key = (capability_id or "").strip()
        if key not in self._capability_to_flow:
            raise UnmappedCapabilityError(
                f"No explicit flow mapping for capability_id={key!r}. "
                f"Known keys: {sorted(self._capability_to_flow)}"
            )
        return self._capability_to_flow[key]

    def _ecu_to_contract(self, ecu: Dict[str, Any]) -> WeaverRouterContract:
        cap = str(ecu.get("capability_id") or "").strip()
        if not cap:
            return WeaverRouterContract(
                flow_id="",
                flow_version="",
                confidence=float(ecu.get("confidence") or 0.0),
                reasoning=str(ecu.get("reason") or ""),
            )
        mapping = self._resolve_mapping(cap)
        return WeaverRouterContract(
            flow_id=mapping.flow_id,
            flow_version=mapping.flow_version,
            confidence=float(ecu.get("confidence") or 0.0),
            reasoning=str(ecu.get("reason") or ""),
        )

    def select_and_execute(
        self,
        user_request: str,
        *,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        started = time.perf_counter()
        ecu = self._wp.decide(user_request)
        decision_id = str(ecu.get("decision_id") or "")
        capability_id = str(ecu.get("capability_id") or "")

        try:
            contract = self._ecu_to_contract(ecu)
        except UnmappedCapabilityError as exc:
            contract = WeaverRouterContract(
                flow_id="",
                flow_version="",
                confidence=float(ecu.get("confidence") or 0.0),
                reasoning=str(ecu.get("reason") or ""),
            )
            trace = WeaverExecutionTrace(
                decision_id=decision_id,
                capability_id=capability_id,
                provider=str(ecu.get("provider") or ""),
                callable=bool(ecu.get("callable")),
                contract=contract,
                ecu=ecu,
                error=str(exc),
            )
            if decision_id:
                self._send_feedback(trace, started, success=False, execution_meta={})
            return self._pack(trace, None)

        trace = WeaverExecutionTrace(
            decision_id=decision_id,
            capability_id=capability_id,
            provider=str(ecu.get("provider") or ""),
            callable=bool(ecu.get("callable")),
            contract=contract,
            ecu=ecu,
        )

        if not decision_id:
            trace.error = "decide returned empty decision_id"
            return self._pack(trace, None)

        if not trace.callable:
            trace.error = "ECU callable=false"
            self._send_feedback(trace, started, success=False, execution_meta={})
            return self._pack(trace, None)

        try:
            self._registry.get_flow(contract.flow_id)
        except Exception as exc:
            trace.error = f"flow not registered: {contract.flow_id} ({exc})"
            self._send_feedback(trace, started, success=False, execution_meta={})
            return self._pack(trace, None)

        # NOTE: flow_version is preserved as advisory audit metadata inside initial_input
        initial_input: Dict[str, Any] = {
            "task": user_request,
            "capability_id": capability_id,
            "provider": trace.provider,
            "execution_type": ecu.get("execution_type"),
            "flow_version": contract.flow_version,
        }
        if context:
            initial_input["context"] = context

        result = self._executor.execute_flow(contract.flow_id, initial_input)
        execution = self._normalize_execution(result)
        trace.execution = execution
        exec_meta = self._extract_chainweaver_metadata(execution, contract, started)
        trace.chainweaver = exec_meta

        ok = bool(execution.get("success"))
        fb = self._send_feedback(trace, started, success=ok, execution_meta=exec_meta)
        trace.feedback = fb

        return self._pack(trace, execution)

    def _send_feedback(
        self,
        trace: WeaverExecutionTrace,
        started: float,
        *,
        success: bool,
        execution_meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not trace.decision_id:
            return {}
        note = self._build_feedback_user_note(trace, execution_meta)
        cost = execution_meta.get("cost_report")
        token_usage = cost if isinstance(cost, dict) else None
        return self._wp.feedback(
            trace.decision_id,
            success=success,
            latency_ms=self._elapsed_ms(started),
            user_note=note,
            token_usage=token_usage,
            result_quality=1.0 if success else 0.0,
        )

    @staticmethod
    def _build_feedback_user_note(
        trace: WeaverExecutionTrace,
        execution_meta: Dict[str, Any],
    ) -> str:
        """JSON-in-string ROI + ChainWeaver trace (aligned with WisePick feedback convention)."""
        payload: Dict[str, Any] = {
            "schema_version": CHAINWEAVER_TRACE_SCHEMA,
            "capability_id": trace.capability_id,
            "flow_id": trace.contract.flow_id,
            "flow_version": trace.contract.flow_version,
            "chainweaver": execution_meta,
        }
        if trace.error:
            payload["error"] = trace.error
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _extract_chainweaver_metadata(
        execution: Dict[str, Any],
        contract: WeaverRouterContract,
        started: float,
    ) -> Dict[str, Any]:
        """Flat execution trace fully aligned with ChainWeaver's ExecutionResult shape."""
        # Aligned to ChainWeaver's real field: total_duration_ms
        total_duration_ms = execution.get("total_duration_ms")
        if total_duration_ms is None:
            total_duration_ms = execution.get("duration_ms") or execution.get("duration")
        if total_duration_ms is None:
            total_duration_ms = WisePickChainWeaverAdapter._elapsed_ms(started)

        # Aligned to ChainWeaver's core fields (trace_id, execution_log, cost_report, times)
        meta: Dict[str, Any] = {
            "trace_id": str(execution.get("trace_id") or uuid.uuid4().hex),
            "total_duration_ms": int(total_duration_ms),
            "cost_report": execution.get("cost_report") if execution.get("cost_report") is not None else execution.get("cost", {}),
            "execution_log": execution.get("execution_log") if isinstance(execution.get("execution_log"), list) else execution.get("log", []),
            "started_at": execution.get("started_at"),
            "ended_at": execution.get("ended_at"),
            "initial_input": execution.get("initial_input", {}),
            "flow_id": contract.flow_id,
            "flow_version": contract.flow_version,
            "success": bool(execution.get("success")),
        }
        return meta

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return max(1, int((time.perf_counter() - started) * 1000))

    @staticmethod
    def _normalize_execution(result: Any) -> Dict[str, Any]:
        """Normalizes Pydantic models or objects into a standardized dict."""
        if hasattr(result, "flow_name") or hasattr(result, "success"):
            # Normalize logs accurately favoring 'execution_log'
            log = getattr(result, "execution_log", None) or getattr(result, "log", None) or []
            out: Dict[str, Any] = {
                "flow_name": getattr(result, "flow_name", ""),
                "success": bool(getattr(result, "success", False)),
                "final_output": getattr(result, "final_output", None),
                "execution_log": [
                    asdict(r) if hasattr(r, "__dataclass_fields__") else r for r in log
                ],
            }
            for attr in (
                "trace_id",
                "total_duration_ms",
                "duration_ms",
                "cost_report",
                "cost",
                "started_at",
                "ended_at",
                "initial_input",
            ):
                if hasattr(result, attr):
                    val = getattr(result, attr)
                    if val is not None:
                        out[attr] = val
            out["log"] = out.get("execution_log", [])
            return out
        if isinstance(result, dict):
            normalized = dict(result)
            if "execution_log" not in normalized and "log" in normalized:
                normalized["execution_log"] = normalized["log"]
            elif "log" not in normalized and "execution_log" in normalized:
                normalized["log"] = normalized["execution_log"]
            return normalized
        return {
            "success": False,
            "final_output": None,
            "execution_log": [],
            "log": [],
        }

    @staticmethod
    def _pack(trace: WeaverExecutionTrace, execution: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "contract": asdict(trace.contract),
            "execution": execution,
            "trace": {
                "decision_id": trace.decision_id,
                "capability_id": trace.capability_id,
                "provider": trace.provider,
                "callable": trace.callable,
                "ecu": trace.ecu,
                "chainweaver": trace.chainweaver,
                "feedback": trace.feedback,
                "error": trace.error,
            },
        }


# --- Test / demo stubs --------------------------------------------------------


@dataclass
class StubExecutionResult:
    flow_name: str
    success: bool
    final_output: Optional[Dict[str, Any]]
    execution_log: List[Any]
    trace_id: str
    total_duration_ms: int
    duration_ms: int
    cost_report: Dict[str, Any]
    started_at: str
    ended_at: str
    initial_input: Dict[str, Any]


class StubFlowRegistry:
    def __init__(self, flow_names: set[str]) -> None:
        self._names = flow_names

    def get_flow(self, flow_name: str) -> str:
        if flow_name not in self._names:
            raise KeyError(flow_name)
        return flow_name


class StubFlowExecutor:
    """Implements FlowExecutorLike for unit tests and local demos."""

    def execute_flow(self, flow_name: str, initial_input: Dict[str, Any]) -> StubExecutionResult:
        return StubExecutionResult(
            flow_name=flow_name,
            success=True,
            final_output={"task": initial_input.get("task")},
            execution_log=[{"step": "done", "tool": "echo"}],
            trace_id=uuid.uuid4().hex,
            total_duration_ms=42,
            duration_ms=42,
            cost_report={"input": 10, "output": 5, "usd": 0.01},
            started_at="2025-01-01T00:00:00Z",
            ended_at="2025-01-01T00:00:00.042Z",
            initial_input=dict(initial_input),
        )