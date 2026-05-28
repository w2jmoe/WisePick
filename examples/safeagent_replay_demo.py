"""
WisePick routing + SafeAgent idempotent replay (stdlib only, no HTTP).

Simulates:
  1. WisePick /v1/decide (stub ECU)
  2. Deterministic SafeAgent request_id from stable turn anchor
  3. First execution (RUN)
  4. Orchestrator retry with a fresh decide (new decision_id, same request_id)
  5. Replay dispatch → SafeAgent SKIP (no duplicate side effects)

Run from repo root:

  python examples/safeagent_replay_demo.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from adapters.safeagent_adapter import (  # noqa: E402
    SAFEAGENT_TRACE_SCHEMA,
    SafeAgentAdapter,
    StubSafeAgentResult,
    StubSafeAgentRuntime,
    wisepick_to_safeagent_request_id,
)

# Orchestrator-owned turn anchor — must stay fixed across retries for distributed idempotency.
TURN_START_TIME_MS = 1_716_780_000_000.0

SESSION_ID = "demo-session-7f3a"
TURN_ID = 1
TASK = "Summarize the quarterly earnings call transcript"
CONSTRAINTS: Dict[str, Any] = {"max_cost_usd": 0.50, "region": "us-east-1"}


def _banner(title: str) -> None:
    line = "-" * 72
    print(f"\n{line}\n  {title}\n{line}")


def _kv(label: str, value: object) -> None:
    print(f"  {label:<22} {value}")


@dataclass(frozen=True)
class SimulatedEcu:
    """Minimal WisePick ECU fields consumed by SafeAgentAdapter."""

    decision_id: str
    capability_id: str
    provider: str
    execution_type: str = "api"
    callable: bool = True
    confidence: float = 0.88
    reason: str = "capability_match (simulated)"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "capability_id": self.capability_id,
            "provider": self.provider,
            "execution_type": self.execution_type,
            "callable": self.callable,
            "confidence": self.confidence,
            "reason": self.reason,
        }


class SimulatedWisePick:
    """
    Stand-in for WisePickClient.decide / feedback.

    Each decide() mints a new decision_id (as a live router would on retry/replan)
    while capability_id/provider stay stable for the same task intent.
    """

    def __init__(self, ecu_template: SimulatedEcu) -> None:
        self._template = ecu_template
        self._decide_count = 0
        self.feedback_log: List[Dict[str, Any]] = []

    def decide(self, task: str) -> Dict[str, Any]:
        self._decide_count += 1
        ecu = SimulatedEcu(
            decision_id=f"dec_retry_{self._decide_count:03d}",
            capability_id=self._template.capability_id,
            provider=self._template.provider,
            execution_type=self._template.execution_type,
            callable=self._template.callable,
            confidence=self._template.confidence,
            reason=self._template.reason,
        )
        return ecu.as_dict()

    def feedback(
        self,
        decision_id: str,
        success: bool,
        latency_ms: int,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        row = {
            "decision_id": decision_id,
            "success": success,
            "latency_ms": latency_ms,
            **kwargs,
        }
        self.feedback_log.append(row)
        return {"ok": True, "decision_id": decision_id}


@dataclass(frozen=True)
class ExecutionOutcome:
    """SafeAgent-style disposition for idempotent dispatch."""

    disposition: str  # RUN | SKIP
    request_id: str
    success: bool
    output: Optional[Dict[str, Any]]
    trace_id: str
    duration_ms: int


class IdempotentSafeAgentRuntime:
    """
    Production SafeAgent deduplicates by request_id.

    Wraps StubSafeAgentRuntime: first sighting RUNs the stub; duplicates SKIP
    without invoking side-effecting work again.
    """

    def __init__(self, inner: StubSafeAgentRuntime) -> None:
        self._inner = inner
        self._completed: Dict[str, ExecutionOutcome] = {}

    @property
    def inner(self) -> StubSafeAgentRuntime:
        return self._inner

    def execute(self, request: Dict[str, Any]) -> Dict[str, Any]:
        request_id = str(request.get("request_id") or "")
        if request_id in self._completed:
            prior = self._completed[request_id]
            return {
                "success": True,
                "disposition": "SKIP",
                "request_id": request_id,
                "output": {
                    "idempotent_replay": True,
                    "reused_trace_id": prior.trace_id,
                    "first_disposition": prior.disposition,
                },
                "trace_id": prior.trace_id,
                "duration_ms": 0,
            }

        raw = self._inner.execute(request)
        outcome = ExecutionOutcome(
            disposition="RUN",
            request_id=request_id,
            success=bool(raw.success),
            output=dict(raw.output) if raw.output else None,
            trace_id=str(raw.trace_id),
            duration_ms=int(raw.duration_ms),
        )
        self._completed[request_id] = outcome
        return {
            "success": outcome.success,
            "disposition": outcome.disposition,
            "request_id": request_id,
            "output": outcome.output,
            "trace_id": outcome.trace_id,
            "duration_ms": outcome.duration_ms,
        }


def _execution_view(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Read execution fields from adapter.select_and_execute() output."""
    execution = payload.get("execution") or {}
    disposition = execution.get("disposition")
    if disposition is None and execution.get("success"):
        disposition = "RUN"
    return {**execution, "disposition": disposition}


def _print_execution(label: str, execution: Dict[str, Any]) -> None:
    _kv("disposition", execution.get("disposition", "n/a"))
    _kv("success", execution.get("success"))
    _kv("trace_id", execution.get("trace_id"))
    _kv("duration_ms", execution.get("duration_ms"))
    out = execution.get("output")
    if out is not None:
        _kv("output", json.dumps(out, ensure_ascii=False))


def main() -> None:
    print("WisePick -> SafeAgent replay / idempotency demo")
    print(f"schema: {SAFEAGENT_TRACE_SCHEMA}")

    template = SimulatedEcu(
        decision_id="dec_placeholder",
        capability_id="general_content",
        provider="chatgpt",
    )
    wisepick = SimulatedWisePick(template)
    stub = StubSafeAgentRuntime()
    runtime = IdempotentSafeAgentRuntime(stub)
    adapter = SafeAgentAdapter(wisepick=wisepick, runtime=runtime)  # type: ignore[arg-type]

    # --- Phase 1: initial route (WisePick owns routing) -----------------------
    _banner("1. WisePick route (simulated POST /v1/decide)")
    route = adapter.route(
        TASK,
        session_id=SESSION_ID,
        turn_id=TURN_ID,
        constraints=CONSTRAINTS,
        start_time=TURN_START_TIME_MS,
    )
    _kv("decision_id", route.decision_id)
    _kv("capability_id", route.capability_id)
    _kv("provider", route.provider)
    _kv("execution_type", route.execution_type)
    _kv("callable", route.callable)
    _kv("confidence", f"{route.confidence:.2f}")
    _kv("request_id", route.request_id)

    expected_request_id = wisepick_to_safeagent_request_id(
        session_id=SESSION_ID,
        turn_id=TURN_ID,
        task=TASK,
        capability_id=template.capability_id,
        provider=template.provider,
        start_time_ms=TURN_START_TIME_MS,
        constraints=CONSTRAINTS,
    )
    _kv("expected_request_id", expected_request_id)
    ids_match = route.request_id == expected_request_id
    _kv("request_id deterministic", "PASS" if ids_match else "FAIL")
    if not ids_match:
        raise SystemExit(1)

    # --- Phase 2: first execution (SafeAgent RUN) ------------------------------
    _banner("2. First execution (SafeAgent RUN)")
    # Bind feedback to this decision_id for WisePick learning telemetry.
    first = adapter.select_and_execute(
        TASK,
        session_id=SESSION_ID,
        turn_id=TURN_ID,
        constraints=CONSTRAINTS,
        start_time=TURN_START_TIME_MS,
    )
    first_exec = _execution_view(first)
    _kv("decision_id (trace)", first["trace"]["decision_id"])
    _kv("request_id", first["request_id"])
    _print_execution("execution", first_exec)
    _kv("stub invoke count", len(stub.calls))

    # --- Phase 3: orchestrator retry — new decide, same idempotency key ----------
    _banner("3. Retry after transient failure (new decide, same request_id)")
    # WisePick may return a fresh decision_id on each decide(); SafeAgent request_id
    # intentionally excludes decision_id so retries reuse the same execution slot.
    retry_route = adapter.route(
        TASK,
        session_id=SESSION_ID,
        turn_id=TURN_ID,
        constraints=CONSTRAINTS,
        start_time=TURN_START_TIME_MS,
    )
    _kv("decision_id (retry)", retry_route.decision_id)
    _kv("request_id (retry)", retry_route.request_id)
    _kv("decision_id changed", route.decision_id != retry_route.decision_id)
    _kv("request_id stable", route.request_id == retry_route.request_id)

    # --- Phase 4: replay dispatch (SafeAgent SKIP) -----------------------------
    _banner("4. Replay execution (SafeAgent SKIP - no duplicate side effects)")
    replay = adapter.select_and_execute(
        TASK,
        session_id=SESSION_ID,
        turn_id=TURN_ID,
        constraints=CONSTRAINTS,
        start_time=TURN_START_TIME_MS,
    )
    replay_exec = _execution_view(replay)
    _kv("decision_id (trace)", replay["trace"]["decision_id"])
    _kv("request_id", replay["request_id"])
    _print_execution("execution", replay_exec)
    _kv("stub invoke count", len(stub.calls))

    # --- Phase 5: verification ---------------------------------------------------
    _banner("5. Verification")
    checks = [
        ("request_id unchanged across retry", route.request_id == replay["request_id"]),
        ("first disposition RUN", first_exec.get("disposition") == "RUN"),
        ("replay disposition SKIP", replay_exec.get("disposition") == "SKIP"),
        ("SKIP reports success", replay_exec.get("success") is True),
        ("stub executed once", len(stub.calls) == 1),
        ("two WisePick decides", wisepick._decide_count >= 3),
        ("feedback per completed attempt", len(wisepick.feedback_log) >= 2),
    ]
    all_ok = True
    for name, ok in checks:
        _kv(name, "PASS" if ok else "FAIL")
        all_ok = all_ok and ok

    _banner("Summary")
    print(
        "  WisePick routes each attempt; SafeAgent deduplicates by request_id.\n"
        "  Replays with the same turn anchor must SKIP duplicate work while still\n"
        "  allowing a new decision_id for audit and optional feedback attribution.\n"
    )
    if not all_ok:
        raise SystemExit("One or more checks failed — see output above.")
    print("  All checks passed.")


if __name__ == "__main__":
    main()
