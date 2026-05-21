"""Placeholder name only — no link to any real OmniCore product.

Minimal runtime-agnostic loop:

  task → POST /v1/decide → map capability_id → local handler → POST /v1/feedback
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any, Callable, Dict

BASE = "http://localhost:8000"

# Keys must match capability_id values your WisePick registry can return.
LOCAL_TOOLS: Dict[str, Callable[[str], str]] = {
    "general_content": lambda t: "ok",
}


def _post(path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def one_turn(task: str) -> None:
    d = _post("/v1/decide", {"task": task})
    cap = str(d.get("capability_id") or "")
    did = str(d.get("decision_id") or "")
    if not did:
        return
    if not cap or d.get("callable") is False:
        _post("/v1/feedback", {"decision_id": did, "success": False, "latency_ms": 0})
        return
    fn = LOCAL_TOOLS.get(cap)
    if fn is None:
        _post("/v1/feedback", {"decision_id": did, "success": False, "latency_ms": 0})
        return
    fn(task)
    _post(
        "/v1/feedback",
        {
            "decision_id": did,
            "success": True,
            "latency_ms": 1,
            "result_quality": 1.0,
        },
    )


if __name__ == "__main__":
    one_turn("Reply with a one-line greeting.")
