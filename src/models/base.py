import enum
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class WorkspaceType(enum.StrEnum):
    public_tech = "public_tech"
    project_pack = "project_pack"
    mock_ops = "mock_ops"


class DocumentStatus(enum.StrEnum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    error = "error"
    container = "container"


class DocType(enum.StrEnum):
    tech_doc = "tech_doc"
    sop = "sop"
    runbook = "runbook"
    api_doc = "api_doc"
    log_doc = "log_doc"


class ChunkLanguage(enum.StrEnum):
    en = "en"
    zh = "zh"
    mixed = "mixed"


class JobType(enum.StrEnum):
    ingest_document = "ingest_document"
    reindex_document = "reindex_document"
    batch_ingest = "batch_ingest"
    eval_run = "eval_run"


class JobStatus(enum.StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"
    retrying = "retrying"


class AgentRunStatus(enum.StrEnum):
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    refused = "refused"


class TraceEventStatus(enum.StrEnum):
    success = "success"
    error = "error"
    skipped = "skipped"


class ToolCallStatus(enum.StrEnum):
    success = "success"
    error = "error"


class EntityType(enum.StrEnum):
    document = "document"
    workspace = "workspace"
    eval = "eval"


class RouteType(enum.StrEnum):
    tech_general = "tech_general"
    project_specific = "project_specific"
    troubleshooting = "troubleshooting"
    runbook_generation = "runbook_generation"
    out_of_scope = "out_of_scope"


class RetrievalStage(enum.StrEnum):
    vector = "vector"
    keyword = "keyword"
    rrf = "rrf"
    rerank = "rerank"


class BadCaseType(enum.StrEnum):
    retrieval_miss = "retrieval_miss"
    wrong_workspace = "wrong_workspace"
    bad_citation = "bad_citation"
    missing_citation = "missing_citation"
    wrong_refusal = "wrong_refusal"
    missed_refusal = "missed_refusal"
    wrong_tool_call = "wrong_tool_call"
    tool_failure = "tool_failure"
    low_answer_score = "low_answer_score"
    latency_high = "latency_high"


class SourceType(enum.StrEnum):
    upload = "upload"
    github = "github"
    url = "url"
    mock_sop = "mock_sop"


class WorkspacePolicy(enum.StrEnum):
    public_only = "public_only"
    selected_project_plus_public = "selected_project_plus_public"
    none = "none"
