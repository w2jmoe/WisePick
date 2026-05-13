#!/usr/bin/env python3
"""
Baseline (``HERMES_WISEPICK_ROUTING=0``) vs WisePick (``HERMES_WISEPICK_ROUTING=1``)
on the same task file. Writes per-mode JSONL via ``HERMES_WISEPICK_BENCH_LOG`` and
``summary.json`` under the output directory.

Requires: a **Hermes agent** checkout whose root contains ``run_agent.py`` (see
``HERMES_AGENT_ROOT`` below), model credentials in the environment, and optionally a
running WisePick server at ``WISEPICK_DECIDE_URL``.

This benchmark always constructs ``AIAgent(api_mode="chat_completions")`` so Hermes
uses ``/v1/chat/completions``. That matches OpenAI-compatible gateways that do not
expose the Responses API.

Usage (from this repository root):

  set HERMES_AGENT_ROOT=C:\\path\\to\\hermes-agent
  set OPENAI_API_KEY=...
  set OPENAI_BASE_URL=https://example.com/v1
  python benchmark/runners/wisepick_bench_compare.py ^
    --toolsets hermes-acp,image_gen,tts,code_execution ^
    --model gpt-5.4

Defaults: tasks file ``benchmark/tasks/wisepick_validation_tasks.json``, output
``benchmark/reports/`` (ignored by git except ``.gitkeep``).
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "README_API.md").is_file():
            return parent
    return here.parents[3]


def _find_hermes_agent_root() -> Optional[Path]:
    env = (os.environ.get("HERMES_AGENT_ROOT") or "").strip()
    if env:
        p = Path(env).expanduser().resolve()
        if (p / "run_agent.py").is_file():
            return p
        return None
    repo = _repo_root()
    for name in ("hermes-agent", "hermes_agent"):
        p = (repo.parent / name).resolve()
        if p.is_dir() and (p / "run_agent.py").is_file():
            return p
    return None


def _load_tasks(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return list(data.get("tasks") or [])


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _index_by_task_id(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        tid = r.get("task_id")
        if tid:
            out[str(tid)] = r
    return out


def _aggregate(
    baseline: Dict[str, Dict[str, Any]],
    wisepick: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    ids = sorted(set(baseline) & set(wisepick))
    if not ids:
        return {"error": "no overlapping task_id between logs"}

    def _nums(key: str, src: Dict[str, Dict[str, Any]]) -> List[float]:
        return [float(src[i].get(key) or 0) for i in ids]

    b_tools = _nums("total_tool_calls", baseline)
    w_tools = _nums("total_tool_calls", wisepick)
    b_api = _nums("api_call_count", baseline)
    w_api = _nums("api_call_count", wisepick)
    b_inv = _nums("invalid_tool_rounds", baseline)
    w_inv = _nums("invalid_tool_rounds", wisepick)

    first_same = 0
    for i in ids:
        bf = baseline[i].get("first_tool_name")
        wf = wisepick[i].get("first_tool_name")
        if bf and wf and bf == wf:
            first_same += 1

    aligned = []
    primed = 0
    for i in ids:
        r = wisepick[i]
        if r.get("whether_wisepick_primed"):
            primed += 1
            v = r.get("first_tool_matches_wisepick_primed")
            if v is True:
                aligned.append(1.0)
            elif v is False:
                aligned.append(0.0)

    return {
        "tasks_compared": len(ids),
        "first_tool_same_across_modes_rate": first_same / len(ids),
        "avg_total_tool_calls_baseline": statistics.mean(b_tools) if b_tools else 0.0,
        "avg_total_tool_calls_wisepick": statistics.mean(w_tools) if w_tools else 0.0,
        "avg_api_call_count_baseline": statistics.mean(b_api) if b_api else 0.0,
        "avg_api_call_count_wisepick": statistics.mean(w_api) if w_api else 0.0,
        "avg_invalid_tool_rounds_baseline": statistics.mean(b_inv) if b_inv else 0.0,
        "avg_invalid_tool_rounds_wisepick": statistics.mean(w_inv) if w_inv else 0.0,
        "avg_execution_path_length_baseline": statistics.mean(b_api) if b_api else 0.0,
        "avg_execution_path_length_wisepick": statistics.mean(w_api) if w_api else 0.0,
        "first_tool_matches_wisepick_primed_rate": (
            statistics.mean(aligned) if aligned else None
        ),
        "wisepick_turns_with_primed_tool": primed,
    }


def _run_batch(
    *,
    agent_root: Path,
    mode: str,
    tasks: List[Dict[str, Any]],
    log_path: Path,
    toolsets: List[str],
    model: str,
    max_iterations: int,
    max_tasks: Optional[int],
    base_url: Optional[str],
    api_key: Optional[str],
) -> None:
    os.chdir(agent_root)
    ar = str(agent_root)
    if ar not in sys.path:
        sys.path.insert(0, ar)

    if log_path.exists():
        log_path.unlink()

    os.environ["HERMES_WISEPICK_BENCH_LOG"] = str(log_path)
    os.environ["HERMES_WISEPICK_ROUTING"] = "0" if mode == "baseline" else "1"
    os.environ["HERMES_WISEPICK_BENCH_MODE"] = mode

    from run_agent import AIAgent

    _agent_kw: Dict[str, Any] = {
        "model": model,
        "max_iterations": max_iterations,
        "enabled_toolsets": toolsets,
        "quiet_mode": True,
        "skip_context_files": True,
        "skip_memory": True,
        "api_mode": "chat_completions",
    }
    if base_url:
        _agent_kw["base_url"] = base_url
    if api_key:
        _agent_kw["api_key"] = api_key

    agent = AIAgent(**_agent_kw)

    for idx, t in enumerate(tasks):
        if max_tasks is not None and idx >= max_tasks:
            break
        tid = str(t.get("id") or "")
        cat = str(t.get("category") or "")
        prompt = str(t.get("prompt") or "").strip()
        if not prompt:
            continue
        os.environ["HERMES_WISEPICK_BENCH_TASK_ID"] = tid
        os.environ["HERMES_WISEPICK_BENCH_TASK_CATEGORY"] = cat
        os.environ["HERMES_WISEPICK_BENCH_ITERATION"] = str(idx)
        os.environ["HERMES_WISEPICK_BENCH_TASK_BODY"] = prompt
        try:
            agent.run_conversation(prompt)
        except Exception as exc:
            print(f"[{mode}] task {tid} error: {exc}", file=sys.stderr, flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="WisePick vs baseline bench (JSONL + aggregate JSON).")
    ap.add_argument(
        "--tasks",
        type=Path,
        default=_repo_root() / "benchmark" / "tasks" / "wisepick_validation_tasks.json",
        help="Task JSON (default: benchmark/tasks/wisepick_validation_tasks.json)",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=_repo_root() / "benchmark" / "reports",
        help="Output directory for baseline.jsonl, wisepick.jsonl, summary.json",
    )
    ap.add_argument(
        "--toolsets",
        default="hermes-acp,image_gen,tts,code_execution",
        help="Comma-separated enabled toolsets",
    )
    ap.add_argument("--model", default=os.environ.get("HERMES_BENCH_MODEL", "anthropic/claude-3.5-haiku"))
    ap.add_argument(
        "--base-url",
        default=os.environ.get("HERMES_BENCH_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or None,
        help="Optional OpenAI-compatible base URL. Falls back to Hermes config when omitted.",
    )
    ap.add_argument(
        "--api-key",
        default=os.environ.get("HERMES_BENCH_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or None,
        help="Optional API key; when omitted, Hermes resolves keys like the CLI.",
    )
    ap.add_argument("--max-iterations", type=int, default=12)
    ap.add_argument("--max-tasks", type=int, default=None, help="Limit number of tasks (debug)")
    ap.add_argument("--baseline-only", action="store_true")
    ap.add_argument("--wisepick-only", action="store_true")
    args = ap.parse_args()

    agent_root = _find_hermes_agent_root()
    if agent_root is None:
        print(
            "Hermes agent root not found. Set HERMES_AGENT_ROOT to the directory "
            "that contains run_agent.py, or place a sibling folder named hermes-agent.",
            file=sys.stderr,
        )
        return 2

    tasks_path: Path = args.tasks
    if not tasks_path.is_file():
        print(f"Tasks file not found: {tasks_path}", file=sys.stderr)
        return 2

    tasks = _load_tasks(tasks_path)
    if not (os.environ.get("HERMES_WISEPICK_BENCH_RUN_UUID") or "").strip():
        os.environ["HERMES_WISEPICK_BENCH_RUN_UUID"] = str(uuid.uuid4())
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    baseline_log = out_dir / "baseline.jsonl"
    wisepick_log = out_dir / "wisepick.jsonl"
    toolsets = [x.strip() for x in str(args.toolsets).split(",") if x.strip()]
    _base_url = str(args.base_url).strip() if getattr(args, "base_url", None) else ""
    _base_url_opt: Optional[str] = _base_url or None
    _api_key = str(args.api_key).strip() if getattr(args, "api_key", None) else ""
    _api_key_opt: Optional[str] = _api_key or None

    if not args.wisepick_only:
        print("=== Baseline (HERMES_WISEPICK_ROUTING=0) ===", flush=True)
        _run_batch(
            agent_root=agent_root,
            mode="baseline",
            tasks=tasks,
            log_path=baseline_log,
            toolsets=toolsets,
            model=args.model,
            max_iterations=args.max_iterations,
            max_tasks=args.max_tasks,
            base_url=_base_url_opt,
            api_key=_api_key_opt,
        )

    if not args.baseline_only:
        print("=== WisePick (HERMES_WISEPICK_ROUTING=1) ===", flush=True)
        _run_batch(
            agent_root=agent_root,
            mode="wisepick",
            tasks=tasks,
            log_path=wisepick_log,
            toolsets=toolsets,
            model=args.model,
            max_iterations=args.max_iterations,
            max_tasks=args.max_tasks,
            base_url=_base_url_opt,
            api_key=_api_key_opt,
        )

    if args.baseline_only or args.wisepick_only:
        summary = {
            "note": "single_mode_run",
            "baseline_only": args.baseline_only,
            "wisepick_only": args.wisepick_only,
            "hermes_api_mode": "chat_completions",
        }
    else:
        summary = _aggregate(
            _index_by_task_id(_load_jsonl(baseline_log)),
            _index_by_task_id(_load_jsonl(wisepick_log)),
        )
        if isinstance(summary, dict):
            summary["hermes_api_mode"] = "chat_completions"

    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {summary_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
