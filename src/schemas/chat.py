from uuid import UUID

from pydantic import BaseModel

from src.schemas.shared import CitationItem, ToolCallItem


class ChatRequest(BaseModel):
    query: str
    workspace_slug: str | None = None


class ChatResponse(BaseModel):
    query_id: UUID
    run_id: UUID
    route: str
    route_confidence: float
    workspace_ids: list[str]
    answer: str
    citations: list[CitationItem]
    confidence_score: float
    refused: bool
    refusal_reason: str | None
    latency_ms: int
    tool_calls: list[ToolCallItem] | None


class FeedbackRequest(BaseModel):
    thumbs: str | None = None
    rating: int | None = None
    correction: str | None = None
    comment: str | None = None


class FeedbackResponse(BaseModel):
    id: UUID
    query_id: UUID
    status: str = "accepted"
