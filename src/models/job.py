from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, EntityType, JobStatus, JobType, TimestampMixin


class BackgroundJob(TimestampMixin, Base):
    __tablename__ = "background_jobs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    arq_job_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    job_type: Mapped[JobType] = mapped_column(
        Enum(JobType, name="job_type"), nullable=False
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"), nullable=False
    )
    entity_type: Mapped[EntityType] = mapped_column(
        Enum(EntityType, name="entity_type"), nullable=False
    )
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(256), nullable=True, unique=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    progress: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=None)
    input_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=None)
    result_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=None)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
