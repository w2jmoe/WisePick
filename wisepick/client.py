"""Minimal WisePick HTTP client (stdlib only)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


class WisePickClient:
    def __init__(self, api_url: str = "http://localhost:8000") -> None:
        self._base = api_url.rstrip("/")

    def _post(self, path: str, body: dict, timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        req = urllib.request.Request(
            f"{self._base}{path}",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
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

    def decide(self, task: str) -> dict:
        task_s = (task or "").strip()
        if not task_s:
            return {}
        return self._post("/v1/decide", {"task": task_s}) or {}

    def inject_openai_choice(self, api_kwargs: dict, task: str) -> dict:
        ecu = self.decide(task)
        cap = str(ecu.get("capability_id") or "").strip()
        if cap and ecu.get("callable") is not False and api_kwargs.get("tools"):
            api_kwargs["tool_choice"] = {
                "type": "function",
                "function": {"name": cap},
            }
        return api_kwargs

    def feedback(
        self,
        decision_id: str,
        success: bool,
        error_message: str | None = None,
    ) -> dict:
        body: Dict[str, Any] = {"decision_id": decision_id, "success": success}
        if error_message:
            body["user_note"] = error_message
        return self._post("/v1/feedback", body) or {}
