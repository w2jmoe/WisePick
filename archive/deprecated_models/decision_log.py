from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSON

from app.core.database import Base


class ApiDecisionLog(Base):
    __tablename__ = "api_decision_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    decision_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    task: Mapped[str] = mapped_column(Text, nullable=False)
    chosen_tool: Mapped[str] = mapped_column(String(100), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    candidates: Mapped[dict] = mapped_column(JSON, nullable=True)
    fallback_plan: Mapped[dict] = mapped_column(JSON, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=True)
    detected_capabilities: Mapped[Any] = mapped_column(JSON, nullable=True)
    candidate_tools: Mapped[Any] = mapped_column(JSON, nullable=True)
    filtered_out_tools: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
