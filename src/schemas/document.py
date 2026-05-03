from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class DocumentUploadResponse(BaseModel):
    document_id: UUID
    job_id: UUID
    status: str = "queued"


class DocumentListItem(BaseModel):
    id: UUID
    workspace_id: UUID
    workspace_slug: str
    title: str
    file_name: str
    doc_type: str
    status: str
    chunk_count: int
    file_size: int
    created_at: datetime
    indexed_at: datetime | None


class DocumentListResponse(BaseModel):
    items: list[DocumentListItem]
    total: int
    limit: int
    offset: int


class DocumentDetail(BaseModel):
    id: UUID
    workspace_id: UUID
    title: str
    file_name: str
    source_type: str
    doc_type: str
    status: str
    error_message: str | None
    chunk_count: int
    embedding_model: str | None
    embedding_dim: int | None
    index_version: int
    created_at: datetime
    updated_at: datetime
    indexed_at: datetime | None


class DocumentDeleteResponse(BaseModel):
    document_id: UUID
    mode: str
    record_deleted: bool
    chunks_deleted: int
    jobs_deleted: int
    retrieval_results_deleted: int
    storage_object_deleted: bool | None = None
    storage_bucket: str | None = None
    storage_key: str | None = None
    warning: str | None = None


class JobProgressDetail(BaseModel):
    stage: str
    percent: int
    current: int
    total: int
    message: str


class JobStatusResponse(BaseModel):
    id: UUID
    job_type: str
    status: str
    progress: JobProgressDetail | None
    error_message: str | None
    retry_count: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
