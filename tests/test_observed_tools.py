"""observed_tools upsert SQL compatibility tests."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from dotenv import load_dotenv

from app.services.observed_tools import upsert_observed_tool


@pytest.fixture
def mock_db() -> MagicMock:
    db = MagicMock()
    db.execute.return_value = MagicMock()
    return db


@patch("app.services.observed_tools.observed_tools_exists", return_value=True)
def test_upsert_executes_without_syntax_error(_exists: MagicMock, mock_db: MagicMock) -> None:
    upsert_observed_tool(
        mock_db,
        tool_key="browser_navigate",
        success=True,
        latency_ms=900,
        runtime_name="hermes",
        task="search openai website",
    )
    mock_db.execute.assert_called_once()
    sql = str(mock_db.execute.call_args[0][0])
    assert "::jsonb" not in sql
    assert "CAST(:task_sample AS jsonb)" in sql
    mock_db.commit.assert_called_once()


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="DATABASE_URL not set")
def test_upsert_live_roundtrip() -> None:
    load_dotenv()
    from app.core.database import SessionLocal
    from app.services.schema_compat import observed_tools_exists
    from sqlalchemy import text

    if not observed_tools_exists():
        pytest.skip("observed_tools table missing")

    db = SessionLocal()
    try:
        upsert_observed_tool(
            db,
            tool_key="_test_browser_navigate",
            success=True,
            latency_ms=100,
            task="integration test task",
        )
        row = db.execute(
            text(
                "SELECT tool_key, observation_count FROM observed_tools "
                "WHERE tool_key = '_test_browser_navigate'"
            )
        ).fetchone()
        assert row is not None
        assert int(row[1]) >= 1
        db.execute(text("DELETE FROM observed_tools WHERE tool_key = '_test_browser_navigate'"))
        db.commit()
    finally:
        db.close()
