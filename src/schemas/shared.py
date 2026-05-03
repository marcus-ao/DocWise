from uuid import UUID

from pydantic import BaseModel


class CitationItem(BaseModel):
    chunk_id: UUID
    chunk_uid: str
    document_id: UUID
    document_title: str
    section_path: str | None
    page_number: int | None
    score: float
    quote: str


class ToolCallItem(BaseModel):
    tool_name: str
    call_index: int
    input_json: dict
    output_json: dict | None
    status: str
    latency_ms: int | None
    error_message: str | None


class TraceEventItem(BaseModel):
    node_name: str
    sequence_no: int
    status: str
    latency_ms: int | None
    input_summary: dict | None
    output_summary: dict | None
    error_message: str | None


class RetrievalResultItem(BaseModel):
    chunk_uid: str
    document_title: str
    section_path: str | None
    vector_score: float | None
    keyword_score: float | None
    rrf_score: float | None
    rerank_score: float | None
    final_rank: int | None


class WorkspaceStatsItem(BaseModel):
    slug: str
    name: str
    document_count: int
    chunk_count: int
