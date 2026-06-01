"""Minimal data-quality checks for POST /v1/feedback (v0.2.x anti-pollution)."""

from __future__ import annotations

from typing import Any, Optional

LATENCY_MS_MIN = 1
LATENCY_MS_MAX = 86_400_000  # 24 hours


def validate_tool_key_for_decision(
    client_tool_key: Optional[str],
    selected_tool_key: str,
) -> Optional[str]:
    """
    When the client sends tool_key, it must match the routed decision.
    Returns an error message, or None if valid.
    """
    if client_tool_key is None:
        return None
    if client_tool_key != selected_tool_key:
        return "tool_key does not match decision"
    return None


def feedback_validation_message(errors: list[dict[str, Any]]) -> str:
    """Map Pydantic validation errors to operator-facing messages."""
    for err in errors:
        loc = tuple(err.get("loc") or ())
        field = loc[-1] if loc else None

        if field == "latency_ms":
            return (
                f"latency_ms must be between {LATENCY_MS_MIN} and {LATENCY_MS_MAX}"
            )
        if field == "result_quality":
            return "result_quality must be between 0 and 1"
        if field in ("input", "output") and "token_cost" in loc:
            return "token_cost input and output must be >= 0"
        if field == "token_cost":
            return "token_cost must contain non-negative input and output values"

    first = errors[0] if errors else {}
    msg = first.get("msg")
    if isinstance(msg, str) and msg:
        return msg
    return "invalid feedback request"
