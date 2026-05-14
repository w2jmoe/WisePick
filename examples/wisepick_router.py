"""Runtime-agnostic WisePick routing: POST /v1/decide → tool name + metadata.

This mirrors the payload mapping used by Hermes ``agent.wisepick_tool_router``
without importing Hermes. Intended for copy-paste or side-by-side reference.

Environment (optional):
  WISEPICK_DECIDE_URL   default http://localhost:8000/v1/decide
  WISEPICK_FORCE_TOOL   force a tool name (skips HTTP; for dry runs / tests)
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple, Union

ToolSpec = Union[str, Mapping[str, Any]]

_DEFAULT_URL = "http://localhost:8000/v1/decide"


def _tool_names(available_tools: Iterable[ToolSpec]) -> Tuple[list[str], set[str]]:
    names: list[str] = []
    for item in available_tools:
        if isinstance(item, str):
            n = item.strip()
        elif isinstance(item, Mapping):
            fn = item.get("function")
            nested = str(fn.get("name") or "").strip() if isinstance(fn, Mapping) else ""
            n = str(item.get("name") or nested or "").strip()
        else:
            continue
        if n:
            names.append(n)
    return names, set(names)


def extract_tool_from_decide_payload(data: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, Any]]:
    """Map /v1/decide JSON to a runtime tool name (same order as Hermes)."""
    meta: Dict[str, Any] = {"source": None, "provider": None, "confidence": None}

    def _from_ecu_block(block: dict) -> Optional[str]:
        cap = str(block.get("capability_id") or "").strip()
        if not cap:
            return None
        meta["provider"] = block.get("provider")
        meta["confidence"] = block.get("confidence")
        if block.get("callable") is False:
            return None
        return cap

    ecu = data.get("ecu")
    if isinstance(ecu, dict):
        name = _from_ecu_block(ecu)
        if name:
            meta["source"] = "ecu_nested"
            return name, meta

    cap_top = str(data.get("capability_id") or "").strip()
    if cap_top or data.get("callable") is not None or data.get("provider") is not None:
        name = _from_ecu_block(data)
        if name:
            meta["source"] = "ecu_flat"
            return name, meta

    tc = data.get("tool_call")
    if isinstance(tc, dict):
        key = str(tc.get("tool_key") or "").strip()
        if key:
            meta["source"] = "tool_call.tool_key"
            return key, meta

    agent_ready = data.get("agent_ready_output")
    if isinstance(agent_ready, dict):
        primary = agent_ready.get("primary_choice")
        if isinstance(primary, dict):
            key = str(primary.get("tool_key") or "").strip()
            if key:
                meta["source"] = "agent_ready_output.primary_choice.tool_key"
                return key, meta
            cap = str(primary.get("capability_id") or "").strip()
            if cap and primary.get("callable") is not False:
                meta["source"] = "agent_ready_output.primary_choice.capability_id"
                meta["provider"] = primary.get("provider")
                return cap, meta

    return None, meta


def _post_decide(url: str, task: str, timeout: float) -> Optional[Dict[str, Any]]:
    body = json.dumps({"task": task}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def route_task(
    task: str,
    available_tools: Iterable[ToolSpec],
    *,
    decide_url: Optional[str] = None,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    """Call WisePick once; validate against ``available_tools``; Hermes-compatible fallback.

    If ``available_tools`` yields a non-empty name set, the routed tool must be
    in that set (same as ``valid_tool_names`` gating in Hermes). If the set is
    empty, any non-empty route is accepted (Hermes skips the membership check).

    Returns:
        ``selected_tool``: str or None (None → caller uses default routing)
        ``provider``: str or None
        ``confidence``: float or int or None (passthrough from payload)
    """
    empty = {"selected_tool": None, "provider": None, "confidence": None}
    task_s = (task or "").strip()
    if not task_s:
        return empty

    _, allowed = _tool_names(available_tools)

    force = (os.environ.get("WISEPICK_FORCE_TOOL") or "").strip()
    if force:
        key = force
        meta = {"provider": None, "confidence": None}
    else:
        url = (decide_url or os.environ.get("WISEPICK_DECIDE_URL") or _DEFAULT_URL).strip() or _DEFAULT_URL
        data = _post_decide(url, task_s, timeout)
        if not data:
            return empty
        key, meta = extract_tool_from_decide_payload(data)
        if not key:
            return {
                "selected_tool": None,
                "provider": meta.get("provider"),
                "confidence": meta.get("confidence"),
            }

    if allowed and key not in allowed:
        return {
            "selected_tool": None,
            "provider": meta.get("provider"),
            "confidence": meta.get("confidence"),
        }

    return {
        "selected_tool": key,
        "provider": meta.get("provider"),
        "confidence": meta.get("confidence"),
    }
