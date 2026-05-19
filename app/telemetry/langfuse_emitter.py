"""
Langfuse routing telemetry (mcp.route_decision.v1).
"""

from __future__ import annotations

import base64
import json
import secrets
import time
import traceback
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.core.logger import get_logger
from app.schemas.decide import DecideRequest, DecideResponse

logger = get_logger("langfuse_emitter")

SCHEMA_VERSION = "mcp.route_decision.v1"
ROUTER_NAME_DEFAULT = "wisepick"

_CONTEXT_TRACE_KEYS = ("trace_id", "langfuse_trace_id")
_CONTEXT_SESSION_KEYS = ("session_id", "langfuse_session_id")

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="langfuse-emit")

def _iso_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

def _extract_id(context: dict[str, Any] | None, keys: tuple[str, ...]) -> str | None:
    if not context:
        return None
    for key in keys:
        val = context.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return None

def _sanitize_arguments(response: DecideResponse) -> dict[str, Any]:
    args: dict[str, Any] = {"confidence": float(response.confidence)}
    trace = response.trace if isinstance(response.trace, dict) else {}
    if "latency_ms" in trace: args["latency_ms"] = int(trace["latency_ms"])
    explain = response.explain if isinstance(response.explain, dict) else {}
    if "candidate_count" in explain: args["candidate_count"] = int(explain["candidate_count"])
    if "feedback_count" in explain: args["feedback_count"] = int(explain["feedback_count"])
    selected = explain.get("selected_capability")
    if isinstance(selected, dict) and "score" in selected: args["selected_score"] = float(selected["score"])
    yantrik = explain.get("yantrik_cluster") or trace.get("yantrik_cluster")
    if isinstance(yantrik, dict) and yantrik.get("configured"):
        args["yantrik_health_penalty_applied"] = bool(yantrik.get("health_penalty_applied"))
    return args

def build_route_decision_payload(request: DecideRequest, response: DecideResponse, *, router_name: str = ROUTER_NAME_DEFAULT) -> dict[str, Any]:
    ctx = request.context if isinstance(request.context, dict) else None
    trace_id = _extract_id(ctx, _CONTEXT_TRACE_KEYS)
    session_id = _extract_id(ctx, _CONTEXT_SESSION_KEYS)
    payload: dict[str, Any] = {
        "metadata": {"schema_version": SCHEMA_VERSION},
        "decision_id": response.decision_id,
        "router_name": router_name,
        "capability_id": response.capability_id,
        "provider": response.provider,
        "execution_type": response.execution_type,
        "callable": bool(response.callable),
        "arguments": _sanitize_arguments(response),
    }
    if trace_id: payload["trace_id"] = trace_id
    if session_id: payload["session_id"] = session_id
    return payload

def _auth_header(public_key: str, secret_key: str) -> str:
    token = base64.b64encode(f"{public_key}:{secret_key}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"

def _hex_id(byte_len: int = 16) -> str:
    return secrets.token_hex(byte_len)

class LangfuseEmitter:
    def __init__(self, public_key: str = "", secret_key: str = "", host: str = "", *, use_otel: bool = False, router_name: str = ROUTER_NAME_DEFAULT, timeout_seconds: float = 5.0) -> None:
        self.public_key = (public_key or "").strip()
        self.secret_key = (secret_key or "").strip()
        self.host = (host or "https://cloud.langfuse.com").strip().rstrip("/")
        self.use_otel = use_otel
        self.router_name = router_name
        self.timeout_seconds = timeout_seconds

    @property
    def enabled(self) -> bool:
        return bool(self.public_key and self.secret_key)

    def emit_route_decision(self, request: DecideRequest, response: DecideResponse, *, router_name: str | None = None) -> None:
        if not self.enabled: return
        contract = build_route_decision_payload(request, response, router_name=router_name or self.router_name)
        try:
            self._post_ingestion_batch(contract)
        except Exception:
            pass

    def _post_json(self, url: str, body: dict[str, Any]) -> int:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", "Authorization": _auth_header(self.public_key, self.secret_key)}, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
            return int(resp.status)

    def _post_ingestion_batch(self, contract: dict[str, Any]) -> None:
        trace_id = contract.get("trace_id") or contract["decision_id"]
        span_id = f"{contract['decision_id']}:route"
        ts = _iso_timestamp()
        batch = {
            "batch": [
                {
                    "id": f"{trace_id}:trace-create",
                    "type": "trace-create",
                    "timestamp": ts,
                    "body": {"id": trace_id, "name": "WisePick Decision", "timestamp": ts},
                },
                {
                    "id": f"{span_id}:create",
                    "type": "span-create",
                    "timestamp": ts,
                    "body": {
                        "traceId": trace_id,
                        "id": span_id,
                        "name": SCHEMA_VERSION,
                        "startTime": ts,
                        "endTime": ts,
                        "metadata": contract.get("metadata"),
                        "output": contract,
                    },
                }
            ]
        }
        self._post_json(f"{self.host}/api/public/ingestion", batch)

def get_langfuse_emitter() -> LangfuseEmitter:
    return LangfuseEmitter(
        public_key=settings.WISEPICK_LANGFUSE_PUBLIC_KEY,
        secret_key=settings.WISEPICK_LANGFUSE_SECRET_KEY,
        host=settings.WISEPICK_LANGFUSE_HOST,
    )

def emit_route_decision_async(request: DecideRequest, response: DecideResponse, *, router_name: str | None = None) -> None:
    emitter = get_langfuse_emitter()
    if not emitter.enabled: return
    _executor.submit(emitter.emit_route_decision, request, response, router_name=router_name)