from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from src.schemas.shared import WorkspaceStatsItem


class BadCaseItem(BaseModel):
    case_id: str
    query: str
    route: str
    bad_case_types: list[str]
    agent_run_id: UUID | None
    eval_run_id: UUID | None


class IndexWorkspaceItem(BaseModel):
    slug: str
    chunk_count: int
    latest_indexed_at: datetime | None


class AdminStatsResponse(BaseModel):
    total_documents: int
    total_chunks: int
    total_queries: int
    total_agent_runs: int
    total_eval_runs: int
    workspaces: list[WorkspaceStatsItem]


class BadCaseListResponse(BaseModel):
    items: list[BadCaseItem]
    total: int


class IndexStatusResponse(BaseModel):
    total_chunks: int
    active_chunks: int
    inactive_chunks: int
    embedding_model: str
    embedding_dim: int
    vector_index_type: str
    workspaces: list[IndexWorkspaceItem]
