"""Hermes-style integration sketch: prime WisePick, then inject ``tool_choice``.

Run from this directory (``cd examples``) or ensure ``examples/`` is on
``PYTHONPATH``. This does not import ``run_agent.AIAgent`` — only the
standalone router and the same OpenAI / Anthropic shapes Hermes uses.

See ``agent/wisepick_tool_router`` + ``AIAgent._prime_wisepick_tool_routing`` /
``_inject_wisepick_tool_choice`` in ``run_agent.py`` for the full production path.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_EX = Path(__file__).resolve().parent
if str(_EX) not in sys.path:
    sys.path.insert(0, str(_EX))

from wisepick_router import route_task  # noqa: E402


def openai_tool_choice(selected: str) -> Dict[str, Any]:
    return {"type": "function", "function": {"name": selected}}


def prime_wisepick_for_turn(
    user_task: str,
    valid_tool_names: List[str],
) -> Optional[str]:
    """Return Hermes ``function.name`` to force on first completion, or None."""
    r = route_task(user_task, valid_tool_names)
    return r.get("selected_tool")


def inject_wisepick_tool_choice(
    api_mode: str,
    api_kwargs: Dict[str, Any],
    wisepick_forced_tool: Optional[str],
) -> None:
    """Mutate ``api_kwargs`` like ``AIAgent._inject_wisepick_tool_choice``."""
    tool = (wisepick_forced_tool or "").strip()
    if not tool:
        return
    if api_mode == "chat_completions" and api_kwargs.get("tools"):
        api_kwargs["tool_choice"] = openai_tool_choice(tool)
        return
    if api_mode == "anthropic_messages":
        api_kwargs["tool_choice"] = tool


def demo_first_completion_kwargs() -> None:
    """Minimal pseudo-flow: prime → build kwargs → inject → clear after first call."""
    task = "Search the repo for TODO and summarize."
    tools = [{"type": "function", "function": {"name": "search_files"}}]
    valid_names = ["search_files", "terminal"]

    forced = prime_wisepick_for_turn(task, valid_names)
    api_kwargs: Dict[str, Any] = {"model": "gpt-4o-mini", "messages": [], "tools": tools}

    inject_wisepick_tool_choice("chat_completions", api_kwargs, forced)
    # After the first provider call returns, production Hermes clears ``_wisepick_forced_tool``.
    print("tool_choice:", api_kwargs.get("tool_choice"))


if __name__ == "__main__":
    demo_first_completion_kwargs()
