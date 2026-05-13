"""Minimal JSONL instrumentation for WisePick decision-layer validation.

Enable with:
  export HERMES_WISEPICK_BENCH_LOG=/path/to/metrics.jsonl

One JSON object per line per ``run_conversation`` completion.
Does not start servers or call external benchmarks.

Optional env (determinism / grouping repeated runs):
  HERMES_WISEPICK_BENCH_RUN_UUID
  HERMES_WISEPICK_BENCH_ITERATION
  HERMES_WISEPICK_BENCH_TASK_BODY   # preferred source for task_fingerprint
  HERMES_WISEPICK_BENCH_MODE        # e.g. baseline | wisepick (compare script)
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
import re
import threading
import time
import unicodedata
from typing import Any, Dict, Optional

_lock = threading.Lock()

# Bound during ``_execute_tool_calls`` so ``model_tools.handle_function_call``
# can attribute JSON tool errors to the active agent without threading ``agent``
# through every registry handler.
_active_bench_agent: contextvars.ContextVar[Optional[Any]] = contextvars.ContextVar(
    "wisepick_bench_active_agent", default=None
)


def log_path() -> Optional[str]:
    p = (os.environ.get("HERMES_WISEPICK_BENCH_LOG") or "").strip()
    return p or None


def is_active() -> bool:
    return bool(log_path())


def push_active_bench_agent(agent: Any) -> contextvars.Token:
    """Return a token for ``pop_active_bench_agent``."""
    return _active_bench_agent.set(agent)


def pop_active_bench_agent(token: contextvars.Token) -> None:
    _active_bench_agent.reset(token)


def _normalize_for_fingerprint(text: str) -> str:
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", str(text)).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def compute_task_fingerprint(text: str) -> str:
    """Stable SHA-256 hex digest of normalized task text (same task → same fp)."""
    norm = _normalize_for_fingerprint(text)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def reset_turn(agent: Any) -> None:
    """Call at the start of each user turn (before WisePick priming)."""
    agent._wb_total_tool_calls = 0
    agent._wb_first_tool_name: Optional[str] = None
    agent._wb_invalid_tool_rounds = 0
    agent._wb_wisepick_primed_tool: Optional[str] = None
    agent._wb_tool_choice_injected = False
    agent._wb_api_mode_at_turn: str = str(getattr(agent, "api_mode", "") or "")
    agent._wb_turn_start_time = time.time()
    agent._wb_ordered_tool_sequence: list[str] = []
    agent._wb_hallucinated_tool_calls = 0
    agent._wb_unavailable_tool_calls = 0


def on_wisepick_primed(agent: Any, tool_name: Optional[str]) -> None:
    if not is_active():
        return
    agent._wb_wisepick_primed_tool = tool_name


def on_tool_choice_injected(agent: Any) -> None:
    if not is_active():
        return
    agent._wb_tool_choice_injected = True


def record_tool_batch_executed(agent: Any, ordered_names: list) -> None:
    """Record one batch of tool calls about to execute (model order)."""
    if not is_active() or not ordered_names:
        return
    agent._wb_total_tool_calls += len(ordered_names)
    if getattr(agent, "_wb_first_tool_name", None) is None:
        agent._wb_first_tool_name = ordered_names[0]
    seq = getattr(agent, "_wb_ordered_tool_sequence", None)
    if seq is None:
        seq = []
        agent._wb_ordered_tool_sequence = seq
    seq.extend(str(n) for n in ordered_names)


def record_initial_tool_name_validation(agent: Any, names: list[str]) -> None:
    """Count model-proposed names not in ``valid_tool_names`` *before* auto-repair."""
    if not is_active() or not names:
        return
    valid = getattr(agent, "valid_tool_names", None) or set()
    h = int(getattr(agent, "_wb_hallucinated_tool_calls", 0) or 0)
    for raw in names:
        if str(raw) not in valid:
            h += 1
    agent._wb_hallucinated_tool_calls = h


def record_invalid_tool_round(agent: Any) -> None:
    if not is_active():
        return
    agent._wb_invalid_tool_rounds += 1


def record_dispatch_error_result(function_name: str, result: str) -> None:
    """If registry dispatch returned a JSON object with a truthy ``error``, count unavailable."""
    if not is_active():
        return
    agent = _active_bench_agent.get()
    if agent is None:
        return
    try:
        obj = json.loads(result)
    except (json.JSONDecodeError, TypeError, ValueError):
        return
    if not isinstance(obj, dict):
        return
    err = obj.get("error")
    if err is None or (isinstance(err, str) and not err.strip()):
        return
    es = str(err).lower()
    if "must be handled by the agent loop" in es:
        return
    agent._wb_unavailable_tool_calls = int(getattr(agent, "_wb_unavailable_tool_calls", 0) or 0) + 1


def append_turn_record(
    agent: Any,
    *,
    result: Dict[str, Any],
    user_preview: str,
    task_body: Optional[str] = None,
) -> None:
    path = log_path()
    if not path:
        return

    primed = getattr(agent, "_wb_wisepick_primed_tool", None)
    first = getattr(agent, "_wb_first_tool_name", None)
    routing_on = os.environ.get("HERMES_WISEPICK_ROUTING", "1").lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    whether_wisepick = bool(routing_on and primed)
    aligned = None
    if whether_wisepick and first and primed:
        aligned = first == primed

    final_response_success = bool(
        result.get("final_response") is not None
        and not result.get("interrupted")
        and not result.get("partial")
        and not result.get("failed", False)
    )

    task_id = (os.environ.get("HERMES_WISEPICK_BENCH_TASK_ID") or "").strip()
    task_category = (os.environ.get("HERMES_WISEPICK_BENCH_TASK_CATEGORY") or "").strip()
    run_uuid = (os.environ.get("HERMES_WISEPICK_BENCH_RUN_UUID") or "").strip() or None
    _iter_raw = (os.environ.get("HERMES_WISEPICK_BENCH_ITERATION") or "").strip()
    benchmark_iteration: Optional[int] = None
    if _iter_raw:
        try:
            benchmark_iteration = int(_iter_raw)
        except ValueError:
            benchmark_iteration = None

    fp_source = (os.environ.get("HERMES_WISEPICK_BENCH_TASK_BODY") or "").strip()
    if not fp_source and isinstance(task_body, str) and task_body.strip():
        fp_source = task_body.strip()
    if not fp_source:
        fp_source = user_preview or ""
    task_fingerprint = compute_task_fingerprint(fp_source)

    turn_start = float(getattr(agent, "_wb_turn_start_time", 0.0) or 0.0)
    turn_end = time.time()
    duration_ms = int(max(0.0, (turn_end - turn_start) * 1000.0)) if turn_start > 0 else 0

    seq = list(getattr(agent, "_wb_ordered_tool_sequence", None) or [])
    unique_tool_count = len(set(seq))
    whether_multiple_tools_used = len(seq) > 1

    row: Dict[str, Any] = {
        "task_id": task_id or None,
        "task_category": task_category or None,
        "user_preview": (user_preview or "")[:500],
        "api_mode": getattr(agent, "_wb_api_mode_at_turn", None) or getattr(agent, "api_mode", None),
        "first_tool_name": first,
        "total_tool_calls": int(getattr(agent, "_wb_total_tool_calls", 0) or 0),
        "invalid_tool_rounds": int(getattr(agent, "_wb_invalid_tool_rounds", 0) or 0),
        "invalid_tool_retries_snapshot": int(getattr(agent, "_invalid_tool_retries", 0) or 0),
        "api_call_count": int(result.get("api_calls") or 0),
        "execution_path_length": int(result.get("api_calls") or 0),
        "final_response_success": final_response_success,
        "whether_wisepick_primed": bool(primed),
        "whether_wisepick_enabled": routing_on,
        "tool_choice_injected": bool(getattr(agent, "_wb_tool_choice_injected", False)),
        "wisepick_primed_tool": primed,
        "first_tool_matches_wisepick_primed": aligned,
        "session_id": getattr(agent, "session_id", None),
    }

    row["turn_start_time"] = turn_start if turn_start > 0 else None
    row["turn_end_time"] = turn_end
    row["duration_ms"] = duration_ms
    row["hallucinated_tool_calls"] = int(getattr(agent, "_wb_hallucinated_tool_calls", 0) or 0)
    row["unavailable_tool_calls"] = int(getattr(agent, "_wb_unavailable_tool_calls", 0) or 0)
    row["task_fingerprint"] = task_fingerprint
    row["run_uuid"] = run_uuid
    row["benchmark_iteration"] = benchmark_iteration
    row["ordered_tool_sequence"] = seq
    row["unique_tool_count"] = unique_tool_count
    row["whether_multiple_tools_used"] = whether_multiple_tools_used
    row["benchmark_mode"] = (os.environ.get("HERMES_WISEPICK_BENCH_MODE") or "").strip() or None

    line = json.dumps(row, ensure_ascii=False) + "\n"
    try:
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with _lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception:
        pass
