"""
Feedback model for WisePick API v0.
"""
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import DateTime, Boolean, Float, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    decision_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_key: Mapped[str] = mapped_column(String(100), nullable=False)
    outcome: Mapped[str] = mapped_column(String(50), nullable=False, default="completed")
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    token_cost: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    result_quality: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    user_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    runtime_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    trace: Mapped[dict] = mapped_column(JSON, nullable=False, default={})
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
