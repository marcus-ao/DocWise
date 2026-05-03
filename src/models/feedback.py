from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    query_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("queries.id"), nullable=False, index=True
    )
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thumbs: Mapped[str | None] = mapped_column(String(8), nullable=True)
    correction: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
