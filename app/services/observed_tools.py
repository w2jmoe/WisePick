"""Observed tools ledger — auto-populated from feedback.actual_tool_used.

No human review, no manual registry. Pure automatic observation.

Schema:
    observed_tools
        tool_key            TEXT UNIQUE  -- the tool that was actually executed
        observation_count   BIGINT       -- total times seen
        success_count       BIGINT
        failure_count       BIGINT
        avg_latency_ms      NUMERIC      -- incremental mean
        avg_result_quality  NUMERIC      -- incremental mean (NULL until first quality report)
        last_*              snapshot fields
        sample_tasks        JSONB[]      -- up to 5 unique raw task texts
        sample_task_signatures JSONB[]   -- up to 5 unique auto-generated signatures
        sample_runtimes     JSONB[]      -- up to 5 unique runtime names seen
        first_seen_at / last_seen_at / updated_at

Promotion to api_tool_specs is done purely by code rules (threshold on
observation_count / success_count), never by human click.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.database import rollback_session
from app.core.logger import get_logger
from app.services.schema_compat import observed_tools_exists

logger = get_logger("observed_tools")

_SAMPLE_MAX = 5


# ---------------------------------------------------------------------------
# Task signature — deterministic, fully automatic
# ---------------------------------------------------------------------------

def task_signature(task: str) -> str:
    """Return a 12-hex deterministic fingerprint of a normalised task string.

    Steps:
      1. Unicode NFKC normalisation
      2. Lowercase
      3. Collapse whitespace/punctuation to single space
      4. SHA-256, take first 12 hex chars
    """
    s = unicodedata.normalize("NFKC", (task or "").strip().lower())
    s = re.sub(r"[\s\W]+", " ", s).strip()
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------

_UPSERT_SQL = """
INSERT INTO observed_tools (
    tool_key,
    observation_count, success_count, failure_count,
    avg_latency_ms, avg_result_quality,
    last_success, last_latency_ms, last_task_text, last_runtime_name,
    sample_tasks, sample_task_signatures, sample_runtimes,
    source, first_seen_at, last_seen_at, updated_at
)
VALUES (
    :tool_key,
    1, :s_inc, :f_inc,
    :latency_ms, :result_quality,
    :success, :latency_ms, :task_text, :runtime_name,
    CAST(:task_sample AS jsonb), CAST(:sig_sample AS jsonb), CAST(:rt_sample AS jsonb),
    'feedback', now(), now(), now()
)
ON CONFLICT (tool_key) DO UPDATE SET
    last_seen_at       = now(),
    updated_at         = now(),
    observation_count  = observed_tools.observation_count + 1,
    success_count      = observed_tools.success_count + :s_inc,
    failure_count      = observed_tools.failure_count + :f_inc,

    -- incremental mean for latency
    avg_latency_ms = (
        observed_tools.avg_latency_ms * observed_tools.observation_count + :latency_ms
    ) / (observed_tools.observation_count + 1),

    -- incremental mean for quality (only when reported)
    avg_result_quality = CASE
        WHEN :result_quality IS NULL THEN observed_tools.avg_result_quality
        WHEN observed_tools.avg_result_quality IS NULL THEN :result_quality
        ELSE (
            observed_tools.avg_result_quality * observed_tools.observation_count
            + :result_quality
        ) / (observed_tools.observation_count + 1)
    END,

    last_success      = :success,
    last_latency_ms   = :latency_ms,
    last_task_text    = :task_text,
    last_runtime_name = COALESCE(:runtime_name, observed_tools.last_runtime_name),

    -- append task text if not already at cap
    sample_tasks = CASE
        WHEN jsonb_array_length(observed_tools.sample_tasks) >= :max_s
        THEN observed_tools.sample_tasks
        ELSE observed_tools.sample_tasks || CAST(:task_sample AS jsonb)
    END,

    -- append signature only if not already present and under cap
    sample_task_signatures = CASE
        WHEN observed_tools.sample_task_signatures @> CAST(:sig_sample AS jsonb)
             OR jsonb_array_length(observed_tools.sample_task_signatures) >= :max_s
        THEN observed_tools.sample_task_signatures
        ELSE observed_tools.sample_task_signatures || CAST(:sig_sample AS jsonb)
    END,

    -- append runtime only if not already present and under cap
    sample_runtimes = CASE
        WHEN :runtime_name IS NULL
             OR observed_tools.sample_runtimes @> CAST(:rt_sample AS jsonb)
             OR jsonb_array_length(observed_tools.sample_runtimes) >= :max_s
        THEN observed_tools.sample_runtimes
        ELSE observed_tools.sample_runtimes || CAST(:rt_sample AS jsonb)
    END
"""


def upsert_observed_tool(
    db: Session,
    *,
    tool_key: str,
    success: bool,
    latency_ms: int = 0,
    result_quality: Optional[float] = None,
    runtime_name: Optional[str] = None,
    task: Optional[str] = None,
) -> None:
    """Upsert an observed-tool entry. Silent no-op when table does not exist."""
    if not observed_tools_exists():
        return

    tool_key = (tool_key or "").strip()
    if not tool_key:
        return

    task_text = (task or "").strip() or None
    sig = task_signature(task_text) if task_text else None

    try:
        db.execute(
            text(_UPSERT_SQL),
            {
                "tool_key": tool_key,
                "s_inc": 1 if success else 0,
                "f_inc": 0 if success else 1,
                "latency_ms": max(latency_ms, 0),
                "result_quality": result_quality,
                "success": success,
                "task_text": task_text,
                "runtime_name": runtime_name,
                "task_sample": json.dumps([task_text] if task_text else []),
                "sig_sample": json.dumps([sig] if sig else []),
                "rt_sample": json.dumps([runtime_name] if runtime_name else []),
                "max_s": _SAMPLE_MAX,
            },
        )
        db.commit()
    except Exception as exc:
        rollback_session(db)
        logger.error(
            "upsert_observed_tool failed tool_key=%s: %s",
            tool_key,
            exc,
            exc_info=True,
        )
