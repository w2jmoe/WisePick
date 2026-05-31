"""
Shared deterministic serialization helpers for WisePick runtime adapters.

Single source of truth for basis-point / millicent encoding, route-token
normalization, and confidence threshold checks (no float comparisons).
"""

from __future__ import annotations

from typing import Any, Mapping

BASIS_POINTS_SCALE = 10_000
USD_MILLICENTS_SCALE = 100_000  # 1 USD = 100_000 millicents
LOW_CONFIDENCE_THRESHOLD_BPS = 100  # 0.01 × 10_000

FALLBACK_CAPABILITY_IDS = frozenset({"none", "general_capability", ""})

ROUTE_LABEL_SEP = "/"


def normalize_route_token(value: str) -> str:
    """Strip and lower-case a capability_id or provider token for stable hashing."""
    return (value or "").strip().lower()


def normalize_capability_id(capability_id: str) -> str:
    return normalize_route_token(capability_id)


def normalize_provider(provider: str) -> str:
    return normalize_route_token(provider)


def confidence_to_basis_points(confidence: float | int) -> int:
    """Map WisePick score in [0, 1] or existing basis points to 0–10000."""
    if isinstance(confidence, int) and confidence > 1:
        if 0 <= confidence <= BASIS_POINTS_SCALE:
            return confidence
        return BASIS_POINTS_SCALE
    value = float(confidence)
    if value > 1.0:
        if value <= BASIS_POINTS_SCALE:
            return int(round(value))
        return BASIS_POINTS_SCALE
    return min(BASIS_POINTS_SCALE, max(0, int(round(value * BASIS_POINTS_SCALE))))


def usd_to_millicents(amount_usd: float) -> int:
    """Convert USD float estimate to integer millicents (replay-safe boundary)."""
    return max(0, int(round(float(amount_usd) * USD_MILLICENTS_SCALE)))


def is_low_confidence_bps(confidence_bps: int) -> bool:
    """Compare routing confidence in basis points only (no float)."""
    return int(confidence_bps) < LOW_CONFIDENCE_THRESHOLD_BPS


def is_low_confidence_from_wire(confidence: float | int) -> bool:
    """Derive basis points first, then apply threshold (hardware-safe)."""
    return is_low_confidence_bps(confidence_to_basis_points(confidence))


def build_reason_codes_from_decide(
    *,
    callable: bool,
    confidence: float | int,
    capability_id: str,
    explain: Mapping[str, Any] | None = None,
) -> list[str]:
    """Structured routing rationale aligned with langfuse_emitter semantics."""
    if not callable:
        return ["fallback_routing"]
    if is_low_confidence_from_wire(confidence):
        return ["fallback_routing"]
    explain = explain or {}
    selected = explain.get("selected_capability")
    if isinstance(selected, dict) and selected.get("matched_capabilities"):
        return ["capability_match"]
    cap = normalize_capability_id(capability_id)
    if cap and cap not in FALLBACK_CAPABILITY_IDS:
        return ["capability_match"]
    return ["fallback_routing"]


def format_route_label(capability_id: str, provider: str) -> str:
    """Canonical route label: ``{capability_id}/{provider}`` (normalized)."""
    cap = normalize_capability_id(capability_id)
    prov = normalize_provider(provider)
    if not cap or not prov:
        raise ValueError("capability_id and provider are required for route label")
    return f"{cap}{ROUTE_LABEL_SEP}{prov}"


def assert_no_floats(obj: Any) -> None:
    """Raise if a JSON-serializable tree contains float (replay wire guard)."""
    if isinstance(obj, float):
        raise TypeError("payload must not contain floats")
    if isinstance(obj, dict):
        for v in obj.values():
            assert_no_floats(v)
    elif isinstance(obj, list):
        for item in obj:
            assert_no_floats(item)
