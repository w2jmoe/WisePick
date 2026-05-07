"""
Decision model for WisePick API v0.
"""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Float, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    decision_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict] = mapped_column(JSON, nullable=False, default={})
    constraints: Mapped[dict] = mapped_column(JSON, nullable=False, default={})
    selected_tool_key: Mapped[str] = mapped_column(String(100), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    explain: Mapped[dict] = mapped_column(JSON, nullable=False, default={})
    trace: Mapped[dict] = mapped_column(JSON, nullable=False, default={})
    bootstrap_version: Mapped[str] = mapped_column(String(20), nullable=False, default="v0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
