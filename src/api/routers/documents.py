"""Document ingestion and management API routes."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from minio import Minio
from sqlalchemy import delete, desc, func, select

from src.api.deps import DbSession, get_minio, get_redis
from src.config.redactor import redact_secrets
from src.config.settings import settings
from src.db.redis import get_redis_client
from src.document.ingestion import enqueue_reindex_job, guess_content_type, submit_document_for_ingestion
from src.models.base import EntityType, JobStatus, JobType
from src.models.document import Document, DocumentChunk
from src.models.job import BackgroundJob
from src.models.query import RetrievalResult
from src.models.workspace import Workspace
from src.schemas.document import (
    DocumentDeleteResponse,
    DocumentDetail,
    DocumentListItem,
    DocumentListResponse,
    DocumentUploadResponse,
    JobProgressDetail,
    JobStatusResponse,
)

router = APIRouter(prefix="/documents", tags=["documents"])


def _minio_client() -> Minio:
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


async def _create_upload_job(**kwargs: object) -> dict:
    return await submit_document_for_ingestion(**kwargs)


@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    db: DbSession,
    file: UploadFile = File(...),
    workspace_slug: str = Form("public_tech"),
    enqueue: bool = Form(True),
) -> DocumentUploadResponse:
    file_bytes = await file.read()
    redis = get_redis_client()
    try:
        result = await _create_upload_job(
            session=db,
            redis=redis,
            minio_client=_minio_client(),
            file_bytes=file_bytes,
            file_name=file.filename or "document.txt",
            workspace_slug=workspace_slug,
            content_type=guess_content_type(file.filename or "", file.content_type),
            enqueue=enqueue,
        )
        if result["job_id"] is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Document already exists and has no active ingestion job",
            )
        return DocumentUploadResponse(
            document_id=result["document_id"],
            job_id=result["job_id"],
            status=str(result["status"]),
        )
    finally:
        await redis.aclose()


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    db: DbSession,
    status_filter: str | None = Query(default=None, alias="status"),
    workspace_slug: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> DocumentListResponse:
    stmt = select(Document, Workspace).join(Workspace, Workspace.id == Document.workspace_id)
    count_stmt = select(func.count()).select_from(Document).join(Workspace, Workspace.id == Document.workspace_id)
    if status_filter and status_filter != "All":
        stmt = stmt.where(Document.status == status_filter)
        count_stmt = count_stmt.where(Document.status == status_filter)
    if workspace_slug:
        stmt = stmt.where(Workspace.slug == workspace_slug)
        count_stmt = count_stmt.where(Workspace.slug == workspace_slug)
    rows = (await db.execute(stmt.order_by(desc(Document.created_at)).limit(limit).offset(offset))).all()
    total = int(await db.scalar(count_stmt) or 0)
    return DocumentListResponse(
        items=[
            DocumentListItem(
                id=document.id,
                workspace_id=document.workspace_id,
                workspace_slug=workspace.slug,
                title=document.title,
                file_name=document.file_name,
                doc_type=str(getattr(document.doc_type, "value", document.doc_type)),
                status=str(getattr(document.status, "value", document.status)),
                chunk_count=document.chunk_count,
                file_size=document.file_size,
                created_at=document.created_at,
                indexed_at=document.indexed_at,
            )
            for document, workspace in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(db: DbSession, job_id: UUID) -> JobStatusResponse:
    job = await db.get(BackgroundJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    progress = JobProgressDetail(**job.progress) if isinstance(job.progress, dict) else None
    return JobStatusResponse(
        id=job.id,
        job_type=str(getattr(job.job_type, "value", job.job_type)),
        status=str(getattr(job.status, "value", job.status)),
        progress=progress,
        error_message=job.error_message,
        retry_count=job.retry_count,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(db: DbSession, document_id: UUID) -> DocumentDetail:
    document = await db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return DocumentDetail(
        id=document.id,
        workspace_id=document.workspace_id,
        title=document.title,
        file_name=document.file_name,
        source_type=document.source_type,
        doc_type=str(getattr(document.doc_type, "value", document.doc_type)),
        status=str(getattr(document.status, "value", document.status)),
        error_message=document.error_message,
        chunk_count=document.chunk_count,
        embedding_model=document.embedding_model,
        embedding_dim=document.embedding_dim,
        index_version=document.index_version,
        created_at=document.created_at,
        updated_at=document.updated_at,
        indexed_at=document.indexed_at,
    )


async def reindex_document(
    db: DbSession,
    document_id: UUID,
    redis: object | None = None,
    _auth: object | None = None,
) -> JobStatusResponse:
    document = await db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    job = await db.scalar(
        select(BackgroundJob)
        .where(BackgroundJob.entity_id == document.id, BackgroundJob.job_type == JobType.reindex_document)
        .order_by(desc(BackgroundJob.created_at))
        .limit(1)
    )
    arq_finished = False
    if job is not None and redis is not None and job.arq_job_id:
        try:
            arq_finished = bool(await redis.exists(f"arq:result:{job.arq_job_id}"))
        except Exception:
            arq_finished = False
    if job is None or JobStatus(getattr(job.status, "value", job.status)) not in ACTIVE_REINDEX_STATUSES or arq_finished:
        if job is None:
            job = BackgroundJob(
                job_type=JobType.reindex_document,
                status=JobStatus.queued,
                entity_type=EntityType.document,
                entity_id=document.id,
                input_json={"document_id": str(document.id)},
                progress={"stage": "queued", "percent": 0, "current": 0, "total": 1, "message": "Queued reindex"},
            )
            db.add(job)
            if hasattr(db, "flush"):
                await db.flush()
            if getattr(job, "id", None) is None:
                from uuid import uuid4

                job.id = uuid4()
        job.status = JobStatus.queued
        job.error_message = None
        job.result_json = None
        job.started_at = None
        job.finished_at = None
        job.progress = {"stage": "queued", "percent": 0, "current": 0, "total": 1, "message": "Queued reindex"}
    try:
        job.arq_job_id = await enqueue_reindex_job(job.id)
    except Exception as exc:
        job.status = JobStatus.failed
        job.error_message = redact_secrets(str(exc))
        await db.commit()
        raise
    await db.commit()
    if hasattr(db, "refresh"):
        await db.refresh(job)
    return JobStatusResponse(
        id=job.id,
        job_type=str(getattr(job.job_type, "value", job.job_type)),
        status=str(getattr(job.status, "value", job.status)),
        progress=JobProgressDetail(**job.progress) if isinstance(job.progress, dict) else None,
        error_message=job.error_message,
        retry_count=job.retry_count,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.post("/{document_id}/retry", response_model=DocumentUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def retry_document(
    db: DbSession,
    document_id: UUID,
    redis: object = Depends(get_redis),
) -> DocumentUploadResponse:
    job = await reindex_document(db, document_id, redis, None)
    return DocumentUploadResponse(document_id=document_id, job_id=job.id, status=job.status)


@router.delete("/{document_id}/record", response_model=DocumentDeleteResponse)
async def delete_document_record(db: DbSession, document_id: UUID) -> DocumentDeleteResponse:
    document = await db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return DocumentDeleteResponse(
        document_id=document_id,
        mode="record",
        record_deleted=False,
        chunks_deleted=0,
        jobs_deleted=0,
        retrieval_results_deleted=0,
        warning="Record-only deletion is a frontend hide action; refresh restores the row.",
    )


async def purge_document(
    db: DbSession,
    minio_client: Minio,
    document_id: UUID,
    _auth: object | None = None,
) -> DocumentDeleteResponse:
    document = await db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    bucket = document.storage_bucket
    key = document.storage_key
    retrieval_result = await db.execute(delete(RetrievalResult).where(RetrievalResult.document_id == document_id))
    retrieval_count = int(retrieval_result.rowcount or 0)
    chunks_result = await db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
    jobs_result = await db.execute(delete(BackgroundJob).where(BackgroundJob.entity_id == document_id))
    document_result = await db.execute(delete(Document).where(Document.id == document_id))

    object_deleted: bool | None = None
    try:
        minio_client.remove_object(bucket, key)
        object_deleted = True
    except Exception:
        object_deleted = False

    await db.commit()
    return DocumentDeleteResponse(
        document_id=document_id,
        mode="record_and_storage",
        record_deleted=True,
        chunks_deleted=int(chunks_result.rowcount or 0),
        jobs_deleted=int(jobs_result.rowcount or 0),
        retrieval_results_deleted=retrieval_count,
        storage_object_deleted=object_deleted,
        storage_bucket=bucket,
        storage_key=key,
        warning=None if int(document_result.rowcount or 0) else "Document row was not deleted.",
    )


@router.delete("/{document_id}", response_model=DocumentDeleteResponse)
async def delete_document(
    db: DbSession,
    document_id: UUID,
    minio_client: Minio = Depends(get_minio),
) -> DocumentDeleteResponse:
    return await purge_document(db, minio_client, document_id, None)


@router.delete("/{document_id}/purge", response_model=DocumentDeleteResponse)
async def purge_document_route(
    db: DbSession,
    document_id: UUID,
    minio_client: Minio = Depends(get_minio),
) -> DocumentDeleteResponse:
    return await purge_document(db, minio_client, document_id, None)


ACTIVE_REINDEX_STATUSES = {JobStatus.queued, JobStatus.running, JobStatus.retrying}
