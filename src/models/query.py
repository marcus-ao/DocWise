from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, RetrievalStage, RouteType


class Query(Base):
    __tablename__ = "queries"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    original_query: Mapped[str] = mapped_column(Text, nullable=False)
    rewritten_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    workspace_slug: Mapped[str | None] = mapped_column(String(128), nullable=True)
    route: Mapped[RouteType | None] = mapped_column(
        Enum(RouteType, name="route_type"), nullable=True
    )
    route_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    refused: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    refusal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RetrievalResult(Base):
    __tablename__ = "retrieval_results"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    query_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("queries.id"), nullable=False, index=True
    )
    run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agent_runs.id"), nullable=False, index=True
    )
    chunk_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("document_chunks.id"), nullable=False
    )
    chunk_uid: Mapped[str] = mapped_column(String(256), nullable=False)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    workspace_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    vector_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    keyword_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rrf_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rerank_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retrieval_stage: Mapped[RetrievalStage] = mapped_column(
        Enum(RetrievalStage, name="retrieval_stage"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
