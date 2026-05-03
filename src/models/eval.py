from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, RouteType


class EvalCase(Base):
    __tablename__ = "eval_cases"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    case_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    route: Mapped[RouteType] = mapped_column(
        Enum(RouteType, name="route_type", create_type=False), nullable=False
    )
    workspace_slug: Mapped[str | None] = mapped_column(String(128), nullable=True)
    expected_workspace_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=None)
    expected_answer_points: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=None)
    expected_chunk_uids: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=None)
    expected_tools: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=None)
    expected_citations: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=None)
    should_refuse: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    tags: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class EvalResult(Base):
    __tablename__ = "eval_results"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    case_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("eval_cases.id"), nullable=False
    )
    agent_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agent_runs.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    retrieval_hit_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    mrr: Mapped[float | None] = mapped_column(Float, nullable=True)
    workspace_accuracy: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    citation_validity: Mapped[float | None] = mapped_column(Float, nullable=True)
    citation_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    refusal_accuracy: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    tool_call_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    answer_correctness: Mapped[float | None] = mapped_column(Float, nullable=True)
    faithfulness: Mapped[float | None] = mapped_column(Float, nullable=True)
    bad_case_types: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=None)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
