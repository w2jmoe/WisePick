"""Lightweight schema capability probes (no migrations at runtime)."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import inspect

from app.core.database import engine


@lru_cache
def _feedback_columns() -> frozenset[str]:
    insp = inspect(engine)
    if not insp.has_table("feedback"):
        return frozenset()
    return frozenset(c["name"] for c in insp.get_columns("feedback"))


def feedback_has_runtime_name() -> bool:
    """True when feedback.runtime_name exists (post migrate_v0_3_0.sql)."""
    return "runtime_name" in _feedback_columns()


def feedback_has_actual_tool_used() -> bool:
    """True when feedback.actual_tool_used exists (post migrate_actual_tool_used.sql)."""
    return "actual_tool_used" in _feedback_columns()


@lru_cache
def observed_tools_exists() -> bool:
    """True when observed_tools table exists (post migrate_v0_3_0.sql)."""
    insp = inspect(engine)
    return insp.has_table("observed_tools")
