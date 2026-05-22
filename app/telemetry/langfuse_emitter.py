"""
Langfuse routing telemetry (mcp.route_decision.v1).
"""

from __future__ import annotations

import base64
import json
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
EXECUTION_FEEDBACK_SCHEMA = "mcp.execution_feedback.v1"
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

def _flat_route_metrics(response: DecideResponse) -> dict[str, Any]:
    """Scalar metrics for mcp.route_decision.v1 metadata (lists added separately)."""
    trace = response.trace if isinstance(response.trace, dict) else {}
    explain = response.explain if isinstance(response.explain, dict) else {}
    metrics: dict[str, Any] = {
        "confidence": float(response.confidence),
        "latency_ms": int(trace.get("latency_ms", 0)),
        "candidate_count": int(explain.get("candidate_count", 0)),
        "feedback_count": int(explain.get("feedback_count", 0)),
    }
    selected = explain.get("selected_capability")
    if isinstance(selected, dict) and "score" in selected:
        metrics["selected_score"] = float(selected["score"])
    yantrik = explain.get("yantrik_cluster") or trace.get("yantrik_cluster")
    if isinstance(yantrik, dict) and yantrik.get("configured"):
        metrics["yantrik_health_penalty_applied"] = bool(yantrik.get("health_penalty_applied"))
        lag = yantrik.get("replication_lag_log_entries")
        if lag is not None:
            metrics["yantrik_replication_lag_log_entries"] = int(lag)
    return metrics


def _build_top_candidates_list(
    response: DecideResponse,
    *,
    selected_tool_key: str,
    selected_capability_id: str,
) -> list[dict[str, Any]]:
    """Map trace.top_candidates to Langfuse mcp.route_decision.v1 list shape."""
    trace = response.trace if isinstance(response.trace, dict) else {}
    raw = trace.get("top_candidates")
    if not isinstance(raw, list):
        return []

    candidates: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        tool_key = str(item.get("provider") or item.get("tool_key") or "").strip()
        capability_id = str(item.get("capability_id") or "general_capability").strip()
        if not tool_key:
            continue
        rank = int(item.get("rank") or len(candidates) + 1)
        score = round(float(item.get("score", 0)), 4)
        candidates.append(
            {
                "rank": rank,
                "tool_key": tool_key,
                "capability_id": capability_id,
                "score": score,
                "selected": (
                    tool_key == selected_tool_key
                    and capability_id == selected_capability_id
                ),
            }
        )

    if candidates and not any(c["selected"] for c in candidates):
        candidates[0]["selected"] = True
    return candidates


def _build_reason_codes(
    response: DecideResponse,
    *,
    callable_out: bool,
    low_confidence_reject: bool,
) -> list[str]:
    if not callable_out:
        return ["no_match_found"]
    if low_confidence_reject:
        return ["no_match_found"]
    explain = response.explain if isinstance(response.explain, dict) else {}
    selected = explain.get("selected_capability")
    if isinstance(selected, dict):
        matched = selected.get("matched_capabilities") or []
        if matched:
            return ["capability_match"]
    cap = (response.capability_id or "").strip()
    if cap and cap not in ("none", "general_capability"):
        return ["capability_match"]
    return ["no_match_found"]


def build_route_decision_payload(
    request: DecideRequest,
    response: DecideResponse,
    *,
    router_name: str = ROUTER_NAME_DEFAULT,
) -> dict[str, Any]:
    """
    Build mcp.route_decision.v1 contract for Langfuse ingestion.

    Uses fresh UUIDs for trace_id / decision_id to avoid duplicate batch IDs (HTTP 207).
    """
    import uuid

    decision_id = uuid.uuid4().hex
    trace_id = uuid.uuid4().hex

    confidence = float(response.confidence)
    callable_out = bool(response.callable)
    capability_id: str = response.capability_id
    provider: str = response.provider
    low_confidence_reject = confidence < 0.01

    selected_tool_key = provider
    selected_capability_id = capability_id

    if low_confidence_reject:
        callable_out = False
        capability_id = "none"
        provider = "none"
        top_candidates: list[dict[str, Any]] = []
        reason_codes = ["no_match_found"]
    else:
        top_candidates = _build_top_candidates_list(
            response,
            selected_tool_key=selected_tool_key,
            selected_capability_id=selected_capability_id,
        )
        reason_codes = _build_reason_codes(
            response,
            callable_out=callable_out,
            low_confidence_reject=False,
        )
        if not callable_out:
            top_candidates = []
            reason_codes = ["no_match_found"]

    ctx = request.context if isinstance(request.context, dict) else None
    session_id = _extract_id(ctx, _CONTEXT_SESSION_KEYS)
    upstream_trace_id = _extract_id(ctx, _CONTEXT_TRACE_KEYS)

    metrics = _flat_route_metrics(response)
    metadata: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "decision_id": decision_id,
        "trace_id": trace_id,
        "wisepick_decision_id": response.decision_id,
        "router_name": router_name,
        "capability_id": capability_id,
        "provider": provider,
        "execution_type": response.execution_type,
        "callable": callable_out,
        "top_candidates": top_candidates,
        "reason_codes": reason_codes,
        **metrics,
    }
    if session_id:
        metadata["session_id"] = session_id
    if upstream_trace_id:
        metadata["upstream_trace_id"] = upstream_trace_id

    output: dict[str, Any] = {
        "capability_id": capability_id,
        "provider": provider,
        "callable": callable_out,
        "confidence": confidence,
        "latency_ms": metrics["latency_ms"],
        "reason_codes": reason_codes,
        "top_candidates_count": len(top_candidates),
    }

    return {
        "metadata": metadata,
        "decision_id": decision_id,
        "trace_id": trace_id,
        "output": output,
    }

def _auth_header(public_key: str, secret_key: str) -> str:
    token = base64.b64encode(f"{public_key}:{secret_key}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"

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
        if not self.enabled:
            return
        contract = build_route_decision_payload(request, response, router_name=router_name or self.router_name)
        try:
            self._post_ingestion_batch(contract)
        except Exception as e:
            logger.error(f"Langfuse Emitter Error: {e}", exc_info=True)

    def _post_json(self, url: str, body: dict[str, Any]) -> int:
        payload_json = json.dumps(body, ensure_ascii=False)
        logger.info("Langfuse POST %s payload: %s", url, payload_json)
        data = payload_json.encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": _auth_header(self.public_key, self.secret_key),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                status_code = int(resp.status)
                resp_body = resp.read().decode("utf-8", errors="replace")
                if status_code != 200:
                    logger.error(
                        "Langfuse post non-200: status=%s body=%s",
                        status_code,
                        resp_body,
                    )
                else:
                    logger.info(f"Langfuse post status: {status_code}")
                return status_code
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            logger.error(
                "Langfuse HTTP error: status=%s body=%s",
                e.code,
                err_body,
                exc_info=True,
            )
            raise

    def emit_execution_feedback(self, contract: dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            self._post_execution_feedback_batch(contract)
        except Exception as e:
            logger.error(f"Langfuse Emitter Error: {e}", exc_info=True)

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
                        "output": contract.get("output"),
                    },
                },
            ]
        }
        status_code = self._post_json(f"{self.host}/api/public/ingestion", batch)
        if status_code != 200:
            logger.error(
                "Langfuse ingestion batch (route) non-200: status=%s decision_id=%s trace_id=%s",
                status_code,
                contract.get("decision_id"),
                contract.get("trace_id"),
            )

    def _post_execution_feedback_batch(self, contract: dict[str, Any]) -> None:
        trace_id = contract.get("trace_id") or contract["decision_id"]
        parent_span_id = contract.get("parent_span_id") or f"{contract['decision_id']}:route"
        exec_span_id = f"{contract['decision_id']}:execution"
        ts = _iso_timestamp()
        batch = {
            "batch": [
                {
                    "id": f"{exec_span_id}:create",
                    "type": "span-create",
                    "timestamp": ts,
                    "body": {
                        "traceId": trace_id,
                        "id": exec_span_id,
                        "parentObservationId": parent_span_id,
                        "name": EXECUTION_FEEDBACK_SCHEMA,
                        "startTime": ts,
                        "endTime": ts,
                        "metadata": contract.get("metadata"),
                        "output": contract.get("output"),
                    },
                },
            ]
        }
        status_code = self._post_json(f"{self.host}/api/public/ingestion", batch)
        if status_code != 200:
            logger.error(
                "Langfuse ingestion batch (execution feedback) non-200: status=%s decision_id=%s",
                status_code,
                contract.get("decision_id"),
            )

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

def build_execution_feedback_payload(
    *,
    decision_id: str,
    tool_key: str,
    success: bool,
    latency_ms: int,
    token_cost: dict[str, Any] | None = None,
    result_quality: float | None = None,
    decision_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ctx = decision_context if isinstance(decision_context, dict) else {}
    trace_id = _extract_id(ctx, _CONTEXT_TRACE_KEYS) or decision_id
    session_id = _extract_id(ctx, _CONTEXT_SESSION_KEYS)
    route_span_id = f"{decision_id}:route"
    args: dict[str, Any] = {
        "success": bool(success),
        "latency_ms": int(latency_ms),
        "tool_key": tool_key,
    }
    if token_cost:
        args["token_cost"] = token_cost
    if result_quality is not None:
        args["result_quality"] = float(result_quality)
        
    meta_payload = {
        "schema_version": EXECUTION_FEEDBACK_SCHEMA,
        "decision_id": decision_id,
        "success": bool(success),
        "tool_key": tool_key,
    }
    if session_id:
        meta_payload["session_id"] = session_id

    payload: dict[str, Any] = {
        "metadata": meta_payload,
        "decision_id": decision_id,
        "parent_span_id": route_span_id,
        "output": args,
    }
    payload["trace_id"] = trace_id
    return payload

def emit_execution_feedback_async(
    *,
    decision_id: str,
    tool_key: str,
    success: bool,
    latency_ms: int,
    token_cost: dict[str, Any] | None = None,
    result_quality: float | None = None,
    decision_context: dict[str, Any] | None = None,
) -> None:
    emitter = get_langfuse_emitter()
    if not emitter.enabled:
        return
    contract = build_execution_feedback_payload(
        decision_id=decision_id,
        tool_key=tool_key,
        success=success,
        latency_ms=latency_ms,
        token_cost=token_cost,
        result_quality=result_quality,
        decision_context=decision_context,
    )
    _executor.submit(emitter.emit_execution_feedback, contract)