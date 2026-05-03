"""Pydantic schemas for Agent tool inputs and outputs."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RetrievedChunkItem(BaseModel):
    chunk_uid: str
    content: str
    score: float
    document_title: str
    section_path: str | None
    workspace_id: str


class SearchDocsOutput(BaseModel):
    chunks: list[RetrievedChunkItem]


class ServiceInfo(BaseModel):
    service_name: str
    display_name: str
    owner: str
    env: str
    tier: str
    sla: str
    dependencies: list[str] = Field(default_factory=list)
    runbooks: list[str] = Field(default_factory=list)
    dashboards: list[str] = Field(default_factory=list)
    log_sources: list[str] = Field(default_factory=list)


class ProjectManifestOutput(BaseModel):
    matched_services: list[ServiceInfo]
    dependencies: list[str]
    runbooks: list[str]
    confidence: float


class MetricsInfo(BaseModel):
    cpu_percent: float
    memory_percent: float
    error_rate_5m: float
    p95_latency_ms: float


class AlertInfo(BaseModel):
    severity: str
    name: str
    started_at: str


class ServiceStatusOutput(BaseModel):
    service_name: str
    status: Literal["healthy", "degraded", "down", "unknown"]
    metrics: MetricsInfo
    active_alerts: list[AlertInfo]
    checked_at: str


class LogEntry(BaseModel):
    timestamp: str
    service_name: str
    component: str
    level: str
    message: str
    trace_id: str | None = None
    request_id: str | None = None
    error_code: str | None = None
    metadata: dict | None = None


class QueryLogsOutput(BaseModel):
    service_name: str
    time_range: str
    matched_count: int
    entries: list[LogEntry]
    summary: str


class RunbookCitation(BaseModel):
    chunk_uid: str
    document_title: str
    section_path: str | None
    quote: str


class RunbookDraftOutput(BaseModel):
    title: str
    severity: str
    symptoms: list[str]
    diagnosis_steps: list[str]
    mitigation_steps: list[str]
    rollback_steps: list[str]
    citations: list[RunbookCitation]
