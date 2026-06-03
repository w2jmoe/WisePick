"""Lightweight schema capability probes (no migrations at runtime)."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import inspect

from app.core.database import engine


@lru_cache
def feedback_has_runtime_name() -> bool:
    """True when feedback.runtime_name exists (post migrate_runtime_name.sql)."""
    insp = inspect(engine)
    if not insp.has_table("feedback"):
        return False
    cols = {c["name"] for c in insp.get_columns("feedback")}
    return "runtime_name" in cols
