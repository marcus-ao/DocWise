from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import func as sa_func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import AgentRunStatus, Base, RouteType, ToolCallStatus, TraceEventStatus


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("query_id", "turn_index", name="uq_agent_runs_query_turn"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    query_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("queries.id"), nullable=False, index=True
    )
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    parent_run_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    original_query: Mapped[str] = mapped_column(Text, nullable=False)
    route: Mapped[RouteType | None] = mapped_column(
        Enum(RouteType, name="route_type", create_type=False), nullable=True
    )
    route_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    workspace_policy: Mapped[str | None] = mapped_column(String(64), nullable=True)
    workspace_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=None)
    status: Mapped[AgentRunStatus] = mapped_column(
        Enum(AgentRunStatus, name="agent_run_status"), nullable=False
    )
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_citations: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=None)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    refused: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    refusal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    langfuse_trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=None)
    token_usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agent_runs.id"), nullable=False, index=True
    )
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    call_index: Mapped[int] = mapped_column(Integer, nullable=False)
    input_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    output_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=None)
    status: Mapped[ToolCallStatus] = mapped_column(
        Enum(ToolCallStatus, name="tool_call_status"), nullable=False
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TraceEvent(Base):
    __tablename__ = "trace_events"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agent_runs.id"), nullable=False, index=True
    )
    node_name: Mapped[str] = mapped_column(String(64), nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[TraceEventStatus] = mapped_column(
        Enum(TraceEventStatus, name="trace_event_status"), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=None)
    output_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=None)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # NOTE: Python attr is `trace_metadata` because `metadata` is reserved by SQLAlchemy
    # DeclarativeBase. DB column name remains "metadata" per contract.
    trace_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=sa_func.now()
    )
