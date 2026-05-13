from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from src.schemas.shared import CitationItem, TraceEventItem


class ChatConversationListItem(BaseModel):
    id: UUID
    query_id: UUID
    run_id: UUID | None
    title: str
    is_archived: bool = False
    workspace_id: str | None
    workspace_slug: str | None
    created_at: datetime
    updated_at: datetime
    message_count: int
    route: str | None
    status: str | None


class ChatConversationListResponse(BaseModel):
    items: list[ChatConversationListItem]
    total: int
    limit: int
    offset: int


class ChatConversationMessage(BaseModel):
    id: str
    role: str
    content: str
    citations: list[CitationItem] = Field(default_factory=list)
    created_at: datetime


class ChatConversationDetail(BaseModel):
    id: UUID
    query_id: UUID
    run_id: UUID | None
    title: str
    is_archived: bool = False
    workspace_id: str | None
    workspace_slug: str | None
    created_at: datetime
    updated_at: datetime
    status: str | None = None
    messages: list[ChatConversationMessage]
    trace_events: list[TraceEventItem] = Field(default_factory=list)


class TraceListItem(BaseModel):
    run_id: UUID
    query_id: UUID
    query: str
    route: str | None
    status: str
    latency_ms: int | None
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None


class TraceListResponse(BaseModel):
    items: list[TraceListItem]
    total: int
    limit: int
    offset: int


class TraceTimelineNode(BaseModel):
    id: str
    title: str
    type: str
    start_time_ms: int
    end_time_ms: int
    duration_ms: int
    indent_level: int
    status: str
    metadata: dict = Field(default_factory=dict)
    error_message: str | None = None


class TraceTimelineResponse(BaseModel):
    run_id: UUID
    total_latency_ms: int
    nodes: list[TraceTimelineNode]


class EvalTrendItem(BaseModel):
    run_id: UUID
    run_name: str
    hit_rate_at_5: float | None
    mrr: float | None
    citation_accuracy: float | None
    bad_case_count: int
    total_cases: int
    created_at: datetime


class EvalTrendsResponse(BaseModel):
    trends: list[EvalTrendItem]


class EvalBadCaseItem(BaseModel):
    eval_result_id: UUID
    run_id: UUID
    case_id: str
    query: str
    bad_case_types: list[str]
    error_message: str | None
    created_at: datetime


class EvalBadCaseListResponse(BaseModel):
    items: list[EvalBadCaseItem]
    total: int


class LabHistoryTurn(BaseModel):
    query: str
    answer: str
    tool_facts: list[str] = Field(default_factory=list)


class LabRewriterInfo(BaseModel):
    used: bool
    route: str
    original_query: str
    rewritten_query: str
    effective_query: str
    fallback_reason: str
    missing_entities: list[str] = Field(default_factory=list)
    diagnostic_hint: str | None = None


class LabCompareRequest(BaseModel):
    query: str
    workspace_ids: list[str] = Field(default_factory=lambda: ["public_tech"])
    strategies: list[str] = Field(default_factory=lambda: ["vector_only", "hybrid_rerank"])
    top_k: int = Field(default=5, ge=1, le=20)
    rrf_k: int = Field(default=60, ge=1, le=500)
    rerank_top_k: int | None = Field(default=None, ge=1, le=20)
    use_rewriter: bool = True
    route_override: Literal["tech_general", "project_specific", "troubleshooting", "runbook_generation"] | None = None
    recent_turns: list[LabHistoryTurn] | None = None
    context_summary: str | None = None


class LabChunkResult(BaseModel):
    id: str
    chunk_uid: str | None
    score: float
    text: str
    doc_name: str
    document_id: str | None
    section_path: str | None
    page_number: int | None


class LabCompareResponse(BaseModel):
    results: dict[str, list[LabChunkResult]]
    overlap_matrix: dict[str, float]
    timing_ms: dict[str, int]
    degraded: bool = False
    errors: dict[str, str] = Field(default_factory=dict)
    rewriter: LabRewriterInfo


class WorkspaceItem(BaseModel):
    id: UUID
    slug: str
    name: str
    workspace_type: str
    project_name: str | None
    description: str | None
    is_active: bool


class WorkspaceListResponse(BaseModel):
    items: list[WorkspaceItem]


class DocumentChunkItem(BaseModel):
    id: UUID
    chunk_uid: str
    index: int
    content: str
    token_count: int
    char_count: int
    section_title: str | None
    section_path: str | None
    heading_level: int | None
    page_number: int | None
    metadata: dict = Field(default_factory=dict)
    language: str
    created_at: datetime
    updated_at: datetime


class DocumentChunksResponse(BaseModel):
    document_id: UUID
    chunks: list[DocumentChunkItem]
    total: int
    limit: int
    offset: int
