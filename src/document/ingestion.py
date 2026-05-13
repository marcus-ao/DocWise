"""Document upload, parsing, embedding, and database ingestion orchestration."""
from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import re
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import structlog
from arq.connections import RedisSettings, create_pool
from minio import Minio
from redis.asyncio import Redis
from sqlalchemy import delete, desc, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.common.minio import ensure_minio_bucket
from src.config.redactor import redact_secrets
from src.config.settings import settings
from src.db.session import async_session_factory
from src.document.chunker import ChunkDraft, chunk_document
from src.document.doc_type_classifier import classify_doc_type
from src.document.embedder import embed_batch, get_embedding_dim
from src.document.parser import (
    infer_content_type,
    parse_document_bytes,
    render_parsed_document_bytes,
    split_large_document,
)
from src.models.base import DocType, DocumentStatus, EntityType, JobStatus, JobType
from src.models.document import Document, DocumentChunk
from src.models.job import BackgroundJob
from src.models.query import RetrievalResult
from src.models.workspace import Workspace
from src.tasks.helpers import update_job_progress, update_job_status

logger = structlog.get_logger(__name__)
DB_DEDUPE_ONLY_LOCK_TOKEN = "db-dedupe-only"
ACTIVE_JOB_STATUSES = {JobStatus.queued, JobStatus.running, JobStatus.retrying}
TERMINAL_JOB_STATUSES = {JobStatus.succeeded, JobStatus.failed, JobStatus.cancelled}
TERMINAL_DOCUMENT_STATUSES = {DocumentStatus.ready, DocumentStatus.container}


def compute_content_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def sanitize_filename(file_name: str) -> str:
    name = Path(file_name).name.replace("\\", "/").split("/")[-1]
    stem = Path(name).stem
    suffix = Path(name).suffix.lower()
    clean_stem = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "-", stem).strip(".-")
    clean_stem = clean_stem[: max(1, 255 - len(suffix))]
    return f"{clean_stem or 'document'}{suffix}"[:255]


def guess_content_type(file_name: str, content_type: str | None = None) -> str:
    guessed = content_type or mimetypes.guess_type(file_name)[0]
    return infer_content_type(file_name, guessed)


def build_storage_key(workspace_id: UUID, document_id: UUID, file_name: str) -> str:
    return f"{workspace_id}/{document_id}/{sanitize_filename(file_name)}"


def _resolved_doc_type(
    doc_type: DocType | None,
    file_name: str,
    provenance: dict | None,
) -> DocType:
    if doc_type is not None:
        return doc_type
    relative_path = provenance.get("original_path") if isinstance(provenance, dict) else None
    source_path = str(relative_path or file_name)
    return classify_doc_type(source_path)


def _merge_mapping(base: dict | None, updates: dict | None) -> dict | None:
    merged: dict[str, object] = {}
    if isinstance(base, dict):
        merged.update(base)
    if isinstance(updates, dict):
        merged.update({key: value for key, value in updates.items() if value is not None})
    return merged or None


def _redis_settings() -> RedisSettings:
    from urllib.parse import urlparse

    parsed = urlparse(settings.redis_url)
    database = int(parsed.path.strip("/") or "0")
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=database,
        password=parsed.password,
    )


async def _enqueue_arq_job(function_name: str, job_id: UUID) -> str:
    redis = await create_pool(_redis_settings())
    try:
        arq_job = await redis.enqueue_job(function_name, str(job_id))
        return arq_job.job_id if arq_job else ""
    finally:
        await redis.aclose()


async def enqueue_ingest_job(job_id: UUID) -> str:
    return await _enqueue_arq_job("process_ingest_document", job_id)


async def enqueue_reindex_job(job_id: UUID) -> str:
    return await _enqueue_arq_job("process_reindex", job_id)


async def _arq_result_exists(redis: Redis | None, arq_job_id: str | None) -> bool:
    if redis is None or not arq_job_id:
        return False
    try:
        return bool(await redis.exists(f"arq:result:{arq_job_id}"))
    except Exception as error:  # noqa: BLE001 - a Redis probe failure should not block dedupe.
        await logger.awarning("arq_result_probe_failed", arq_job_id=arq_job_id, error=redact_secrets(str(error)))
        return False


async def _ensure_existing_ingest_job_enqueued(
    session: AsyncSession,
    redis: Redis | None,
    document: Document,
    job: BackgroundJob | None,
    workspace_slug: str,
) -> BackgroundJob:
    needs_enqueue = job is None
    if job is not None:
        job_status = JobStatus(getattr(job.status, "value", job.status))
        arq_finished = await _arq_result_exists(redis, job.arq_job_id)
        needs_enqueue = job_status in TERMINAL_JOB_STATUSES or not job.arq_job_id or (
            job_status in ACTIVE_JOB_STATUSES and arq_finished
        )

    if job is None:
        job = BackgroundJob(
            job_type=JobType.ingest_document,
            status=JobStatus.queued,
            entity_type=EntityType.document,
            entity_id=document.id,
            dedupe_key=f"ingest:{document.workspace_id}:{document.content_hash}",
            priority=0,
            progress={
                "stage": "queued",
                "percent": 0,
                "current": 0,
                "total": 1,
                "message": "Queued document ingestion",
            },
            input_json={"document_id": str(document.id), "workspace_slug": workspace_slug},
        )
        session.add(job)
        await session.flush()

    if needs_enqueue:
        document.status = DocumentStatus.pending
        document.error_message = None
        job.status = JobStatus.queued
        job.error_message = None
        job.result_json = None
        job.started_at = None
        job.finished_at = None
        job.progress = {
            "stage": "queued",
            "percent": 0,
            "current": 0,
            "total": 1,
            "message": "Queued document ingestion",
        }
        job.arq_job_id = await enqueue_ingest_job(job.id)
        await session.commit()

    return job


async def _find_existing_document(
    session: AsyncSession,
    workspace_id: UUID,
    file_hash: str,
) -> tuple[Document | None, BackgroundJob | None]:
    document = await session.scalar(
        select(Document)
        .where(Document.workspace_id == workspace_id, Document.content_hash == file_hash)
        .order_by(desc(Document.created_at))
        .limit(1)
    )
    if document is None:
        return None, None
    job = await session.scalar(
        select(BackgroundJob)
        .where(BackgroundJob.entity_id == document.id, BackgroundJob.job_type == JobType.ingest_document)
        .order_by(desc(BackgroundJob.created_at))
        .limit(1)
    )
    return document, job


def _ingest_lock_key(file_hash: str) -> str:
    return f"lock:ingest:{file_hash}"


async def _acquire_ingest_lock(redis: Redis | None, file_hash: str) -> str | None:
    if redis is None:
        return DB_DEDUPE_ONLY_LOCK_TOKEN
    token = uuid4().hex
    try:
        return token if await redis.set(_ingest_lock_key(file_hash), token, ex=1800, nx=True) else None
    except Exception as error:  # noqa: BLE001 - lock failure degrades to DB dedupe.
        await logger.awarning("ingest_lock_failed", error=redact_secrets(str(error)))
        return DB_DEDUPE_ONLY_LOCK_TOKEN


async def _release_ingest_lock(redis: Redis | None, file_hash: str, token: str | None) -> None:
    if redis is None or token in {None, DB_DEDUPE_ONLY_LOCK_TOKEN}:
        return
    key = _ingest_lock_key(file_hash)
    try:
        value = await redis.get(key)
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        if value == token:
            await redis.delete(key)
    except Exception as error:  # noqa: BLE001 - lock release is best effort.
        await logger.awarning("ingest_lock_release_failed", error=redact_secrets(str(error)))


async def _remove_minio_object(minio_client: Minio, bucket: str, key: str) -> None:
    try:
        await asyncio.to_thread(minio_client.remove_object, bucket, key)
    except Exception as error:  # noqa: BLE001 - cleanup failure should be observable but not mask the original error.
        await logger.awarning("orphaned_minio_object_cleanup_failed", key=key, error=redact_secrets(str(error)))


async def _minio_object_exists(minio_client: Minio, bucket: str, key: str) -> bool:
    try:
        await asyncio.to_thread(minio_client.stat_object, bucket, key)
        return True
    except Exception:
        return False


async def _put_minio_object(
    minio_client: Minio,
    bucket: str,
    key: str,
    file_bytes: bytes,
    content_type: str,
) -> None:
    await ensure_minio_bucket(minio_client, bucket)
    await asyncio.to_thread(
        minio_client.put_object,
        bucket,
        key,
        BytesIO(file_bytes),
        len(file_bytes),
        content_type=content_type,
    )


async def _restore_missing_minio_object(
    minio_client: Minio,
    document: Document,
    file_bytes: bytes,
) -> None:
    if await _minio_object_exists(minio_client, document.storage_bucket, document.storage_key):
        return
    await _put_minio_object(
        minio_client=minio_client,
        bucket=document.storage_bucket,
        key=document.storage_key,
        file_bytes=file_bytes,
        content_type=document.content_type,
    )
    await logger.awarning(
        "missing_minio_object_restored",
        document_id=str(document.id),
        storage_bucket=document.storage_bucket,
        storage_key=document.storage_key,
    )


def _normalizer_provenance_updates(parsed) -> dict | None:
    normalizer_meta = parsed.metadata.get("normalizer") if isinstance(parsed.metadata, dict) else None
    if not isinstance(normalizer_meta, dict):
        return None
    return {
        "original_format": normalizer_meta.get("original_format"),
        "normalizer": normalizer_meta.get("tool"),
        "cache_hit": normalizer_meta.get("cache_hit"),
        "normalized_at": normalizer_meta.get("normalized_at"),
        "normalizer_fallback": normalizer_meta.get("tool") == "mineru_fallback_local",
    }


def _apply_parsed_metadata(document: Document, parsed) -> None:
    document.title = parsed.title
    document.parser_name = parsed.parser_name
    document.parser_version = parsed.parser_version

    frontmatter = parsed.metadata.get("frontmatter") if isinstance(parsed.metadata, dict) else None
    if isinstance(frontmatter, dict) and frontmatter:
        document.document_metadata = _merge_mapping(
            document.document_metadata,
            {"frontmatter": frontmatter},
        )

    provenance_updates = _normalizer_provenance_updates(parsed)
    if provenance_updates:
        document.provenance = _merge_mapping(document.provenance, provenance_updates)


def _parsed_content_hash(parsed) -> str:
    # Split children are logical markdown subsections, so their content hash is
    # anchored to the rendered child markdown bytes instead of a raw-file range.
    return compute_content_hash(render_parsed_document_bytes(parsed))


def _anchored_original_path(document: Document, slug: str) -> str:
    provenance = document.provenance if isinstance(document.provenance, dict) else {}
    original_path = provenance.get("original_path") if isinstance(provenance, dict) else None
    base_path = str(original_path).strip() if isinstance(original_path, str) and original_path.strip() else document.file_name
    return f"{base_path}#{slug}"


async def _delete_document_tree(session: AsyncSession, document_id: UUID) -> None:
    descendant_ids = (
        await session.scalars(select(Document.id).where(Document.parent_document_id == document_id))
    ).all()
    for descendant_id in descendant_ids:
        await _delete_document_tree(session, descendant_id)
    await session.execute(delete(RetrievalResult).where(RetrievalResult.document_id == document_id))
    await session.execute(delete(BackgroundJob).where(BackgroundJob.entity_id == document_id))
    await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
    await session.execute(delete(Document).where(Document.id == document_id))


async def _delete_child_documents(
    session: AsyncSession,
    parent_document_id: UUID,
    keep_document_ids: set[UUID] | None = None,
) -> None:
    child_documents = (
        await session.scalars(select(Document).where(Document.parent_document_id == parent_document_id))
    ).all()
    keep_ids = keep_document_ids or set()
    for child_document in child_documents:
        if child_document.id in keep_ids:
            continue
        await _delete_document_tree(session, child_document.id)


async def _load_child_documents(session: AsyncSession, parent_document_id: UUID) -> list[Document]:
    return (
        await session.scalars(select(Document).where(Document.parent_document_id == parent_document_id).order_by(Document.created_at))
    ).all()


async def _deactivate_document_chunks(session: AsyncSession, document_id: UUID) -> None:
    await session.execute(
        update(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .values(is_active=False)
    )


async def _index_parsed_document(session: AsyncSession, document: Document, parsed) -> int:
    chunks = chunk_document(parsed)
    vectors = await _embed_chunk_drafts(chunks)
    if any(vector is None for vector in vectors):
        raise RuntimeError("Embedding failed for one or more chunks")

    new_version = int(document.index_version or 0) + 1
    for chunk, vector in zip(chunks, vectors, strict=True):
        metadata = chunk.metadata.copy()
        if vector is None:
            metadata["embedding_error"] = True
        existing_chunk = await session.scalar(
            select(DocumentChunk).where(
                DocumentChunk.document_id == document.id,
                DocumentChunk.chunk_uid == chunk.chunk_uid,
            )
        )
        values = {
            "workspace_id": document.workspace_id,
            "chunk_index": chunk.chunk_index,
            "content": chunk.content,
            "content_hash": chunk.content_hash,
            "token_count": chunk.token_count,
            "char_count": chunk.char_count,
            "section_title": chunk.section_title,
            "section_path": chunk.section_path,
            "heading_level": chunk.heading_level,
            "page_number": chunk.page_number,
            "start_char": chunk.start_char,
            "end_char": chunk.end_char,
            "source_anchor": chunk.source_anchor,
            "doc_type": document.doc_type,
            "language": chunk.language,
            "embedding": vector,
            "embedding_model": settings.embedding_model,
            "embedding_dim": get_embedding_dim(),
            "index_version": new_version,
            "is_active": False,
            **_metadata_kwargs(metadata),
        }
        if existing_chunk is None:
            session.add(
                DocumentChunk(
                    chunk_uid=chunk.chunk_uid,
                    document_id=document.id,
                    **values,
                )
            )
        else:
            for key, value in values.items():
                setattr(existing_chunk, key, value)

    await session.flush()
    await _refresh_chunk_search_vectors(session, document.id, new_version)
    await session.execute(
        update(DocumentChunk)
        .where(DocumentChunk.document_id == document.id, DocumentChunk.index_version != new_version)
        .values(is_active=False)
    )
    await session.execute(
        update(DocumentChunk)
        .where(DocumentChunk.document_id == document.id, DocumentChunk.index_version == new_version)
        .values(is_active=True)
    )
    await cleanup_old_chunks(session, document.id)

    document.status = DocumentStatus.ready
    document.error_message = None
    document.chunk_count = len(chunks)
    document.embedding_model = settings.embedding_model
    document.embedding_dim = get_embedding_dim()
    document.index_version = new_version
    document.indexed_at = datetime.now(UTC)
    _apply_parsed_metadata(document, parsed)
    return len(chunks)


async def _refresh_chunk_search_vectors(
    session: AsyncSession,
    document_id: UUID,
    index_version: int,
) -> None:
    await session.execute(
        text("""
            UPDATE document_chunks
            SET content_tsv = to_tsvector(
                CASE
                    WHEN language = 'en' THEN 'english'::regconfig
                    ELSE 'simple'::regconfig
                END,
                coalesce(content, '')
            )
            WHERE document_id = :document_id
              AND index_version = :index_version
        """),
        {"document_id": document_id, "index_version": index_version},
    )


async def submit_document_for_ingestion(
    session: AsyncSession,
    redis: Redis | None,
    minio_client: Minio,
    file_bytes: bytes,
    file_name: str,
    workspace_slug: str,
    content_type: str | None = None,
    doc_type: DocType | None = None,
    source_type: str = "upload",
    source_uri: str | None = None,
    provenance: dict | None = None,
    parent_document_id: UUID | None = None,
    enqueue: bool = True,
) -> dict:
    safe_name = sanitize_filename(file_name)
    file_hash = compute_content_hash(file_bytes)
    resolved_doc_type = _resolved_doc_type(doc_type, file_name, provenance)
    workspace = await session.scalar(select(Workspace).where(Workspace.slug == workspace_slug))
    if workspace is None:
        raise ValueError(f"Unknown workspace_slug: {workspace_slug}")

    existing_document, existing_job = await _find_existing_document(session, workspace.id, file_hash)
    if existing_document is not None:
        provenance_updated = False
        if provenance and hasattr(existing_document, "provenance"):
            existing_document.provenance = _merge_mapping(getattr(existing_document, "provenance", None), provenance)
            provenance_updated = True
        await _restore_missing_minio_object(minio_client, existing_document, file_bytes)
        if enqueue and existing_document.status not in TERMINAL_DOCUMENT_STATUSES:
            existing_job = await _ensure_existing_ingest_job_enqueued(
                session,
                redis,
                existing_document,
                existing_job,
                workspace_slug,
            )
        elif provenance_updated:
            await session.commit()
        return {
            "document_id": existing_document.id,
            "job_id": existing_job.id if existing_job else None,
            "status": existing_job.status.value if enqueue and existing_job else existing_document.status.value,
            "existing": True,
        }

    lock_token = await _acquire_ingest_lock(redis, file_hash)
    if lock_token is None:
        for _ in range(10):
            existing_document, existing_job = await _find_existing_document(session, workspace.id, file_hash)
            if existing_document is not None:
                await _restore_missing_minio_object(minio_client, existing_document, file_bytes)
                if enqueue and existing_document.status not in TERMINAL_DOCUMENT_STATUSES:
                    existing_job = await _ensure_existing_ingest_job_enqueued(
                        session,
                        redis,
                        existing_document,
                        existing_job,
                        workspace_slug,
                    )
                return {
                    "document_id": existing_document.id,
                    "job_id": existing_job.id if existing_job else None,
                    "status": existing_job.status.value if enqueue and existing_job else existing_document.status.value,
                    "existing": True,
                }
            await asyncio.sleep(0.5)
        raise RuntimeError("Document ingestion for this content_hash is already in progress")

    inferred_type = guess_content_type(safe_name, content_type)
    document = Document(
        workspace_id=workspace.id,
        title=Path(safe_name).stem.replace("-", " ").replace("_", " "),
        file_name=safe_name,
        source_type=source_type,
        source_uri=source_uri,
        storage_bucket=settings.minio_bucket,
        storage_key="",
        content_type=inferred_type,
        file_size=len(file_bytes),
        content_hash=file_hash,
        document_metadata=None,
        provenance=provenance,
        parent_document_id=parent_document_id,
        is_container=False,
        doc_type=resolved_doc_type,
        status=DocumentStatus.pending,
        chunk_count=0,
        index_version=0,
    )
    job: BackgroundJob | None = None
    object_uploaded = False
    try:
        session.add(document)
        await session.flush()

        document.storage_key = build_storage_key(workspace.id, document.id, safe_name)
        await _put_minio_object(
            minio_client=minio_client,
            bucket=settings.minio_bucket,
            key=document.storage_key,
            file_bytes=file_bytes,
            content_type=inferred_type,
        )
        object_uploaded = True

        job = BackgroundJob(
            job_type=JobType.ingest_document,
            status=JobStatus.queued,
            entity_type=EntityType.document,
            entity_id=document.id,
            dedupe_key=f"ingest:{workspace.id}:{file_hash}",
            priority=0,
            progress={
                "stage": "queued",
                "percent": 0,
                "current": 0,
                "total": 1,
                "message": "Queued document ingestion",
            },
            input_json={"document_id": str(document.id), "workspace_slug": workspace_slug},
        )
        session.add(job)
        await session.flush()
        await session.commit()
    except IntegrityError:
        await session.rollback()
        if object_uploaded:
            await _remove_minio_object(minio_client, settings.minio_bucket, document.storage_key)
        try:
            existing_document, existing_job = await _find_existing_document(session, workspace.id, file_hash)
            if existing_document is not None:
                return {
                    "document_id": existing_document.id,
                    "job_id": existing_job.id if existing_job else None,
                    "status": existing_document.status.value,
                    "existing": True,
                }
            raise
        finally:
            await _release_ingest_lock(redis, file_hash, lock_token)
    except Exception:
        await session.rollback()
        if object_uploaded:
            await _remove_minio_object(minio_client, settings.minio_bucket, document.storage_key)
        await _release_ingest_lock(redis, file_hash, lock_token)
        raise

    try:
        if enqueue and job is not None:
            try:
                job.arq_job_id = await enqueue_ingest_job(job.id)
            except Exception as error:
                job.status = JobStatus.failed
                job.error_message = redact_secrets(str(error))
                document.status = DocumentStatus.error
                document.error_message = job.error_message
                await session.commit()
                raise
            await session.commit()
        return {
            "document_id": document.id,
            "job_id": job.id if job else None,
            "status": job.status.value,
            "existing": False,
        }
    finally:
        await _release_ingest_lock(redis, file_hash, lock_token)


async def _read_minio_object(minio_client: Minio, bucket: str, key: str) -> bytes:
    def read_object() -> bytes:
        response = minio_client.get_object(bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    return await asyncio.to_thread(read_object)


async def _embed_chunk_drafts(chunks: list[ChunkDraft]) -> list[list[float] | None]:
    try:
        vectors = await embed_batch([chunk.content for chunk in chunks])
        return [vector for vector in vectors]
    except Exception as batch_error:  # noqa: BLE001 - fallback to single-item retries per contract.
        await logger.awarning("embed_batch_failed_falling_back", error=redact_secrets(str(batch_error)))

    vectors: list[list[float] | None] = []
    for chunk in chunks:
        try:
            vector = (await embed_batch([chunk.content], batch_size=1))[0]
        except Exception as error:  # noqa: BLE001 - mark this chunk and continue ingestion.
            await logger.awarning(
                "embed_single_chunk_failed",
                chunk_uid=chunk.chunk_uid,
                error=redact_secrets(str(error)),
            )
            vector = None
        vectors.append(vector)
    return vectors


def _metadata_kwargs(metadata: dict) -> dict:
    if "metadata" in DocumentChunk.__mapper__.attrs.keys():
        return {"metadata": metadata}
    return {"chunk_metadata": metadata}


async def cleanup_old_chunks(session: AsyncSession, document_id: UUID, keep_versions: int = 2) -> None:
    versions = (
        await session.scalars(
            select(DocumentChunk.index_version)
            .where(DocumentChunk.document_id == document_id, DocumentChunk.is_active.is_(False))
            .distinct()
            .order_by(desc(DocumentChunk.index_version))
        )
    ).all()
    versions_to_delete = list(versions[keep_versions:])
    if versions_to_delete:
        await session.execute(
            delete(DocumentChunk).where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.index_version.in_(versions_to_delete),
                DocumentChunk.is_active.is_(False),
            )
        )


async def ingest_document_by_id(document_id: str | UUID, job_id: str | UUID | None = None) -> dict:
    document_uuid = UUID(str(document_id))
    job_uuid = UUID(str(job_id)) if job_id is not None else None
    minio_client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )

    async with async_session_factory() as session:
        document = await session.get(Document, document_uuid)
        if document is None:
            raise ValueError(f"Document not found: {document_uuid}")

        await update_job_status(session, job_uuid, JobStatus.running)
        await update_job_progress(session, job_uuid, "parsing", 10, 0, 1, "Parsing source document")
        document.status = DocumentStatus.processing
        await session.commit()

        try:
            file_bytes = await _read_minio_object(minio_client, document.storage_bucket, document.storage_key)
            parser_file_name = document.file_name
            if isinstance(document.provenance, dict):
                original_path = document.provenance.get("original_path")
                if isinstance(original_path, str) and original_path.strip():
                    parser_file_name = original_path.strip()
            parsed = await parse_document_bytes(file_bytes, parser_file_name, document.content_type)
            sub_documents = split_large_document(parsed)
            total_chunks = 0
            if len(sub_documents) == 1:
                await _delete_child_documents(session, document.id)
                document.parent_document_id = None
                document.is_container = False
                await update_job_progress(session, job_uuid, "chunking", 30, 1, 1, "Chunking document")
                total_chunks = await _index_parsed_document(session, document, parsed)
            else:
                await update_job_progress(
                    session,
                    job_uuid,
                    "splitting",
                    20,
                    len(sub_documents),
                    len(sub_documents),
                    f"Split large document into {len(sub_documents)} sub-documents",
                )
                existing_children = await _load_child_documents(session, document.id)
                existing_children_by_path: dict[str, Document] = {}
                for child_document in existing_children:
                    child_path = child_document.provenance.get("original_path") if isinstance(child_document.provenance, dict) else None
                    if isinstance(child_path, str) and child_path.strip():
                        existing_children_by_path[child_path.strip()] = child_document

                # Preserve historical chunk rows for old single-document
                # retrieval_results instead of hard-deleting them when the
                # document is upgraded into a container.
                await _deactivate_document_chunks(session, document.id)
                document.parent_document_id = None
                document.is_container = True
                document.status = DocumentStatus.container
                document.error_message = None
                document.chunk_count = 0
                document.embedding_model = None
                document.embedding_dim = None
                document.index_version = 0
                document.indexed_at = datetime.now(UTC)
                _apply_parsed_metadata(document, parsed)

                kept_child_ids: set[UUID] = set()
                for sub_document in sub_documents:
                    h1_slug = str(sub_document.metadata.get("h1_slug") or "").strip()
                    if not h1_slug:
                        raise RuntimeError("Split child document is missing h1_slug metadata")
                    child_original_path = _anchored_original_path(document, h1_slug)
                    child_provenance = _merge_mapping(document.provenance, {"original_path": child_original_path})
                    child_document = existing_children_by_path.get(child_original_path)
                    child_file_bytes = render_parsed_document_bytes(sub_document)
                    child_content_hash = _parsed_content_hash(sub_document)

                    if child_document is None:
                        child_document = Document(
                            workspace_id=document.workspace_id,
                            title=sub_document.title,
                            file_name=sub_document.file_name,
                            source_type=document.source_type,
                            source_uri=document.source_uri,
                            storage_bucket=document.storage_bucket,
                            storage_key=document.storage_key,
                            content_type=document.content_type,
                            file_size=len(child_file_bytes),
                            content_hash=child_content_hash,
                            document_metadata=None,
                            provenance=child_provenance,
                            parent_document_id=document.id,
                            is_container=False,
                            doc_type=document.doc_type,
                            status=DocumentStatus.processing,
                            chunk_count=0,
                            index_version=0,
                        )
                        session.add(child_document)
                        await session.flush()
                    else:
                        child_document.title = sub_document.title
                        child_document.file_name = sub_document.file_name
                        child_document.source_type = document.source_type
                        child_document.source_uri = document.source_uri
                        child_document.storage_bucket = document.storage_bucket
                        child_document.storage_key = document.storage_key
                        child_document.content_type = document.content_type
                        child_document.file_size = len(child_file_bytes)
                        child_document.content_hash = child_content_hash
                        child_document.provenance = child_provenance
                        child_document.parent_document_id = document.id
                        child_document.is_container = False
                        child_document.doc_type = document.doc_type
                        child_document.status = DocumentStatus.processing
                        child_document.error_message = None

                    kept_child_ids.add(child_document.id)
                    total_chunks += await _index_parsed_document(session, child_document, sub_document)

                await _delete_child_documents(session, document.id, keep_document_ids=kept_child_ids)
                await update_job_progress(
                    session,
                    job_uuid,
                    "storing",
                    75,
                    total_chunks,
                    total_chunks,
                    f"Indexed {len(kept_child_ids)} sub-documents",
                )

            await update_job_status(
                session,
                job_uuid,
                JobStatus.succeeded,
                result_json={"document_id": str(document.id), "chunk_count": total_chunks},
            )
            await update_job_progress(
                session,
                job_uuid,
                "completed",
                100,
                total_chunks,
                total_chunks,
                "Ingestion completed",
            )
            await session.commit()
            return {
                "document_id": str(document.id),
                "chunk_count": total_chunks,
                "status": document.status.value,
            }
        except Exception as error:
            document.status = DocumentStatus.error
            document.error_message = redact_secrets(str(error))
            await update_job_status(session, job_uuid, JobStatus.failed, error_message=document.error_message)
            await session.commit()
            raise


async def ingest_document_by_job_id(job_id: str | UUID) -> dict:
    async with async_session_factory() as session:
        job = await session.get(BackgroundJob, UUID(str(job_id)))
        if job is None:
            raise ValueError(f"Job not found: {job_id}")
        document_id = job.entity_id
    return await ingest_document_by_id(document_id, job_id)


async def reindex_document_by_job_id(job_id: str | UUID) -> dict:
    return await ingest_document_by_job_id(job_id)
