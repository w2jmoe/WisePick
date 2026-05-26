"""
WisePick → SafeAgent adapter.

Routing: POST /v1/decide (ECU). Execution: SafeAgent runtime dispatch (idempotent request_id).
Feedback: POST /v1/feedback.

Deterministic `request_id` enables SafeAgent replay / deduplication without coupling to
WisePick's per-call `decision_id`.
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Protocol, runtime_checkable

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from wisepick import WisePickClient  # noqa: E402

SAFEAGENT_REQUEST_ID_VERSION = 1
SAFEAGENT_TRACE_SCHEMA = "mcp.safeagent_execution.v1"


def _normalize_task(text: str) -> str:
    return " ".join((text or "").split())


def wisepick_to_safeagent_request_id(
    *,
    session_id: str,
    turn_id: str | int,
    task: str,
    capability_id: str,
    provider: str,
    constraints: Mapping[str, Any] | None = None,
) -> str:
    """
    Deterministic SafeAgent request_id (idempotency key) from stable routing intent.

    Preimage: canonical JSON (sorted keys) → SHA-256 → versioned 16-byte UUID string.
    Excludes WisePick `decision_id` and timestamps so replays with a new decide still
    target the same SafeAgent execution slot when session/turn/task/capability match.
    """
    preimage_obj: dict[str, Any] = {
        "schema_version": SAFEAGENT_REQUEST_ID_VERSION,
        "session_id": (session_id or "").strip(),
        "turn_id": str(turn_id),
        "task": _normalize_task(task),
        "capability_id": (capability_id or "").strip(),
        "provider": (provider or "").strip(),
        "constraints": dict(constraints or {}),
    }
    preimage = json.dumps(
        preimage_obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest = hashlib.sha256(preimage.encode("utf-8")).digest()
    versioned = struct.pack(">H", SAFEAGENT_REQUEST_ID_VERSION) + digest[:14]
    return str(uuid.UUID(bytes=versioned))


@runtime_checkable
class SafeAgentRuntimeLike(Protocol):
    """SafeAgent execution surface: idempotent dispatch by request_id."""

    def execute(self, request: Dict[str, Any]) -> Any: ...


@dataclass(frozen=True)
class SafeAgentRoutingDecision:
    """Public routing contract (WisePick ECU + deterministic SafeAgent request_id)."""

    request_id: str
    decision_id: str
    capability_id: str
    provider: str
    execution_type: str
    confidence: float
    callable: bool
    reasoning: str


@dataclass
class SafeAgentExecutionTrace:
    request_id: str
    decision_id: str
    capability_id: str
    provider: str
    callable: bool
    ecu: Dict[str, Any] = field(default_factory=dict)
    safeagent: Dict[str, Any] = field(default_factory=dict)
    execution: Optional[Dict[str, Any]] = None
    feedback: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class SafeAgentAdapter:
    """
    Production adapter: WisePick decide → SafeAgent dispatch → WisePick feedback.

    Mirrors ChainWeaverAdapter separation: WisePick owns routing; SafeAgent owns execution.
    """

    def __init__(
        self,
        *,
        wisepick: WisePickClient,
        runtime: SafeAgentRuntimeLike,
    ) -> None:
        self._wp = wisepick
        self._runtime = runtime

    def ecu_to_dispatch_request(
        self,
        ecu: Mapping[str, Any],
        *,
        task: str,
        session_id: str,
        turn_id: str | int,
        constraints: Mapping[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Map WisePick ECU JSON to SafeAgent invoke payload (contract alignment)."""
        capability_id = str(ecu.get("capability_id") or "").strip()
        provider = str(ecu.get("provider") or ecu.get("tool_key") or "").strip()
        request_id = wisepick_to_safeagent_request_id(
            session_id=session_id,
            turn_id=turn_id,
            task=task,
            capability_id=capability_id,
            provider=provider,
            constraints=constraints,
        )
        return {
            "schema_version": SAFEAGENT_TRACE_SCHEMA,
            "request_id": request_id,
            "decision_id": str(ecu.get("decision_id") or ""),
            "capability_id": capability_id,
            "provider": provider,
            "execution_type": str(ecu.get("execution_type") or "api"),
            "callable": bool(ecu.get("callable", True)),
            "confidence": float(ecu.get("confidence") or 0.0),
            "task": task,
            "reason": str(ecu.get("reason") or ""),
        }

    def route(
        self,
        user_request: str,
        *,
        session_id: str,
        turn_id: str | int,
        context: Optional[Dict[str, Any]] = None,
        constraints: Optional[Dict[str, Any]] = None,
    ) -> SafeAgentRoutingDecision:
        """Resolve intent via WisePick only (no SafeAgent execution)."""
        ecu = self._wp.decide(user_request)
        dispatch = self.ecu_to_dispatch_request(
            ecu,
            task=user_request,
            session_id=session_id,
            turn_id=turn_id,
            constraints=constraints,
        )
        return SafeAgentRoutingDecision(
            request_id=dispatch["request_id"],
            decision_id=dispatch["decision_id"],
            capability_id=dispatch["capability_id"],
            provider=dispatch["provider"],
            execution_type=dispatch["execution_type"],
            confidence=dispatch["confidence"],
            callable=dispatch["callable"],
            reasoning=dispatch["reason"],
        )

    def select_and_execute(
        self,
        user_request: str,
        *,
        session_id: str,
        turn_id: str | int,
        context: Optional[Dict[str, Any]] = None,
        constraints: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        started = time.perf_counter()
        ecu = self._wp.decide(user_request)
        dispatch = self.ecu_to_dispatch_request(
            ecu,
            task=user_request,
            session_id=session_id,
            turn_id=turn_id,
            constraints=constraints,
        )
        request_id = dispatch["request_id"]
        decision_id = dispatch["decision_id"]
        capability_id = dispatch["capability_id"]
        provider = dispatch["provider"]
        callable_out = dispatch["callable"]

        trace = SafeAgentExecutionTrace(
            request_id=request_id,
            decision_id=decision_id,
            capability_id=capability_id,
            provider=provider,
            callable=callable_out,
            ecu=dict(ecu) if isinstance(ecu, dict) else {},
        )

        if not decision_id:
            trace.error = "decide returned empty decision_id"
            return self._pack(trace, None)

        if not callable_out:
            trace.error = "ECU callable=false"
            self._send_feedback(trace, started, success=False, execution_meta={})
            return self._pack(trace, None)

        if context:
            dispatch["context"] = context

        result = self._runtime.execute(dispatch)
        execution = self._normalize_execution(result)
        trace.execution = execution
        exec_meta = self._extract_safeagent_metadata(execution, request_id, started)
        trace.safeagent = exec_meta

        ok = bool(execution.get("success"))
        fb = self._send_feedback(trace, started, success=ok, execution_meta=exec_meta)
        trace.feedback = fb

        return self._pack(trace, execution)

    def _send_feedback(
        self,
        trace: SafeAgentExecutionTrace,
        started: float,
        *,
        success: bool,
        execution_meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not trace.decision_id:
            return {}
        note = self._build_feedback_user_note(trace, execution_meta)
        return self._wp.feedback(
            trace.decision_id,
            success=success,
            latency_ms=self._elapsed_ms(started),
            user_note=note,
            result_quality=1.0 if success else 0.0,
        )

    @staticmethod
    def _build_feedback_user_note(
        trace: SafeAgentExecutionTrace,
        execution_meta: Dict[str, Any],
    ) -> str:
        payload: Dict[str, Any] = {
            "schema_version": SAFEAGENT_TRACE_SCHEMA,
            "request_id": trace.request_id,
            "capability_id": trace.capability_id,
            "provider": trace.provider,
            "safeagent": execution_meta,
        }
        if trace.error:
            payload["error"] = trace.error
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _extract_safeagent_metadata(
        execution: Dict[str, Any],
        request_id: str,
        started: float,
    ) -> Dict[str, Any]:
        duration_ms = execution.get("duration_ms")
        if duration_ms is None:
            duration_ms = execution.get("total_duration_ms")
        if duration_ms is None:
            duration_ms = SafeAgentAdapter._elapsed_ms(started)
        return {
            "request_id": request_id,
            "trace_id": str(execution.get("trace_id") or uuid.uuid4().hex),
            "duration_ms": int(duration_ms),
            "success": bool(execution.get("success")),
            "output": execution.get("output") if "output" in execution else execution.get("final_output"),
        }

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return max(1, int((time.perf_counter() - started) * 1000))

    @staticmethod
    def _normalize_execution(result: Any) -> Dict[str, Any]:
        if hasattr(result, "success"):
            out: Dict[str, Any] = {
                "success": bool(getattr(result, "success", False)),
                "output": getattr(result, "output", None) or getattr(result, "final_output", None),
            }
            for attr in ("trace_id", "duration_ms", "total_duration_ms", "request_id"):
                if hasattr(result, attr):
                    val = getattr(result, attr)
                    if val is not None:
                        out[attr] = val
            return out
        if isinstance(result, dict):
            return dict(result)
        return {"success": False, "output": None}

    @staticmethod
    def _pack(trace: SafeAgentExecutionTrace, execution: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "request_id": trace.request_id,
            "execution": execution,
            "trace": {
                "request_id": trace.request_id,
                "decision_id": trace.decision_id,
                "capability_id": trace.capability_id,
                "provider": trace.provider,
                "callable": trace.callable,
                "ecu": trace.ecu,
                "safeagent": trace.safeagent,
                "feedback": trace.feedback,
                "error": trace.error,
            },
        }


# --- Test / demo stubs --------------------------------------------------------


@dataclass
class StubSafeAgentResult:
    request_id: str
    success: bool
    output: Optional[Dict[str, Any]]
    trace_id: str
    duration_ms: int


class StubSafeAgentRuntime:
    """Implements SafeAgentRuntimeLike for unit tests and local demos."""

    def __init__(self) -> None:
        self.calls: list[Dict[str, Any]] = []

    def execute(self, request: Dict[str, Any]) -> StubSafeAgentResult:
        self.calls.append(dict(request))
        return StubSafeAgentResult(
            request_id=str(request.get("request_id") or ""),
            success=True,
            output={"task": request.get("task")},
            trace_id=uuid.uuid4().hex,
            duration_ms=25,
        )


__all__ = [
    "SafeAgentAdapter",
    "SafeAgentRoutingDecision",
    "SafeAgentRuntimeLike",
    "StubSafeAgentRuntime",
    "wisepick_to_safeagent_request_id",
    "SAFEAGENT_TRACE_SCHEMA",
]
