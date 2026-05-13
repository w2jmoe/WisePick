"""WisePick ``/v1/decide`` client: map JSON response → Hermes ``function.name``.

This module only performs **HTTP transport** and **response-shape parsing** against
the public ECU fields documented in ``AGENTS.md``. It does **not** implement WisePick
server-side scoring, bootstrap weights, or capability ranking.

Hermes may call ``fetch_wisepick_tool_key`` to prime the first completion when
``HERMES_WISEPICK_ROUTING`` is enabled; ``chat_completions`` / ``anthropic_messages``
paths can receive ``tool_choice`` injection on the first API call (handled in Hermes).
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_URL = "http://localhost:8000/v1/decide"


def wisepick_routing_enabled() -> bool:
    """When false, Hermes skips ``/v1/decide`` entirely (e.g. baseline benchmark runs)."""
    v = (os.environ.get("HERMES_WISEPICK_ROUTING") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def extract_hermes_tool_name_from_decide_payload(data: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, Any]]:
    """Map a WisePick ``/v1/decide`` JSON object to a Hermes ``function.name``.

    Resolution order (first match wins):

    1. Nested ``ecu`` with ``capability_id`` (honours ``callable``).
    2. Top-level ECU fields: ``capability_id`` / ``callable`` / ``provider``.
    3. Legacy ``tool_call.tool_key``.
    4. Optional gateway-style ``agent_ready_output.primary_choice`` (``tool_key`` or
       ``capability_id``), for adapters that wrap the raw ECU.

    Returns ``(tool_name_or_none, meta_dict)`` for logging and benchmarks.
    """
    meta: Dict[str, Any] = {"source": None}
    if not isinstance(data, dict):
        return None, meta

    def _from_ecu_block(block: dict) -> Optional[str]:
        cap = str(block.get("capability_id") or "").strip()
        if not cap:
            return None
        meta["provider"] = block.get("provider")
        meta["execution_type"] = block.get("execution_type")
        meta["confidence"] = block.get("confidence")
        if block.get("callable") is False:
            meta["callable"] = False
            return None
        meta["callable"] = block.get("callable", True)
        return cap or None

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
        if cap_top and data.get("callable") is False:
            meta["source"] = "ecu_flat"
            return None, meta

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


_wisepick_log_final: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "wisepick_log_final", default=False
)


def wisepick_begin_turn(selected_tool: Optional[str]) -> None:
    """Mark whether this turn should log the first registry tool execution."""
    _wisepick_log_final.set(bool(selected_tool))


def wisepick_note_execution(function_name: str) -> None:
    if not _wisepick_log_final.get():
        return
    logger.debug("Bench: first executed registry tool: %s", function_name)
    _wisepick_log_final.set(False)


def fetch_wisepick_tool_key(task: str) -> Optional[str]:
    """POST ``/v1/decide`` and return Hermes tool name, or ``None`` on failure / no route.

    For plumbing checks without a live server, set ``HERMES_WISEPICK_FORCE_TOOL`` to a
    Hermes ``function.name`` that exists in the agent tool registry.
    """
    force = (os.environ.get("HERMES_WISEPICK_FORCE_TOOL") or "").strip()
    if force:
        return force

    url = (os.environ.get("WISEPICK_DECIDE_URL") or _DEFAULT_URL).strip() or _DEFAULT_URL
    body = json.dumps({"task": task}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode("utf-8", errors="replace") if e.fp else ""
        logger.debug("WisePick HTTP %s: %s", e.code, body_txt[:500])
        return None
    except Exception as e:
        logger.debug("WisePick request failed: %s", e)
        return None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.debug("WisePick response is not JSON")
        return None

    if not isinstance(data, dict):
        return None

    key, meta = extract_hermes_tool_name_from_decide_payload(data)
    if key and os.environ.get("HERMES_WISEPICK_DEBUG", "").strip().lower() in ("1", "true", "yes"):
        logger.info("WisePick decide mapped task=%r -> %r meta=%s", task[:120], key, meta)
    return key
