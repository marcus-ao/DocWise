from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from src.schemas.shared import CitationItem, RetrievalResultItem, ToolCallItem, TraceEventItem


class AgentRunRequest(BaseModel):
    query: str
    workspace_slug: str | None = None


class AgentRunStatusResponse(BaseModel):
    id: UUID
    query_id: UUID
    status: str
    route: str | None
    latency_ms: int | None
    created_at: datetime


class AgentTraceResponse(BaseModel):
    run_id: UUID
    status: str
    route: str | None
    answer: str | None
    trace_events: list[TraceEventItem]
    retrieval_results: list[RetrievalResultItem]
    tool_calls: list[ToolCallItem]
    citations: list[CitationItem]
    model_summary: dict | None
    token_usage: dict | None
