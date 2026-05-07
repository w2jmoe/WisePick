from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DecisionDatasetRecord(Base):
    __tablename__ = "decision_dataset"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    decision_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    input: Mapped[Any] = mapped_column(JSONB, nullable=False)
    interpretation: Mapped[Any] = mapped_column(JSONB, nullable=False)
    candidate_set: Mapped[Any] = mapped_column(JSONB, nullable=False)
    decision: Mapped[Any] = mapped_column(JSONB, nullable=False)
    execution_meta: Mapped[Any] = mapped_column(JSONB, nullable=False)
    outcome: Mapped[Any] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
