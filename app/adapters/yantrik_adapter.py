"""
Optional YantrikDB state-aware routing: cluster health for ECU score adjustment.
No DB schema changes; skipped when YANTRIK_DB_URL is unset.
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.core.logger import get_logger

logger = get_logger("yantrik_adapter")

# Log replication lag above this threshold → apply health penalty to ECU scores
REPLICATION_LAG_PENALTY_THRESHOLD = 500
HEALTH_PENALTY_MULTIPLIER = 0.5  # reduce score by 50%


@dataclass
class YantrikClusterHealth:
    """Parsed /v1/health payload (best-effort)."""
    replication_lag_log_entries: int | None
    raw: dict[str, Any] | None


def get_cluster_health(base_url: str, api_key: str = "") -> YantrikClusterHealth | None:
    """
    GET {base_url}/v1/health from YantrikDB and parse replication_lag_log_entries.
    Returns None on any transport/parse failure (caller treats as no signal, no penalty).
    """
    base = (base_url or "").strip()
    if not base:
        return None

    url = f"{base.rstrip('/')}/v1/health"
    req = urllib.request.Request(url, method="GET")
    if (api_key or "").strip():
        req.add_header("Authorization", f"Bearer {api_key.strip()}")

    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=5, context=ctx) as resp:
            body = resp.read().decode("utf-8")
        data = json.loads(body)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        logger.debug("YantrikDB health fetch skipped: %s", e)
        return None
    except Exception as e:  # defensive: never break /v1/decide
        logger.debug("YantrikDB health unexpected error: %s", e)
        return None

    if not isinstance(data, dict):
        return None

    lag: int | None = None
    raw_val = data.get("replication_lag_log_entries")
    if raw_val is not None:
        try:
            lag = int(raw_val)
        except (TypeError, ValueError):
            lag = None

    return YantrikClusterHealth(replication_lag_log_entries=lag, raw=data)


def health_score_multiplier(health: YantrikClusterHealth | None) -> float:
    """1.0 normally; HEALTH_PENALTY_MULTIPLIER when lag exceeds threshold."""
    if health is None:
        return 1.0
    lag = health.replication_lag_log_entries
    if lag is not None and lag > REPLICATION_LAG_PENALTY_THRESHOLD:
        return HEALTH_PENALTY_MULTIPLIER
    return 1.0
