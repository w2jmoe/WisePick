from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, String, Text, Numeric, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ApiToolSpec(Base):
    __tablename__ = "api_tool_specs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tool_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    capabilities: Mapped[str] = mapped_column(Text, nullable=False)  # 逗号分隔的关键词
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    bootstrap_weight: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False, default=0.5000)
    meta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)  # JSON data
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
