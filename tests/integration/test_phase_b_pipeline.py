from __future__ import annotations

import csv
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select

import scripts.export_chunk_index as export_chunk_index
import src.document.ingestion as ingestion_module
from src.models.agent import AgentRun
from src.models.base import AgentRunStatus, ChunkLanguage, DocType, DocumentStatus, RetrievalStage, WorkspaceType
from src.models.document import Document, DocumentChunk
from src.models.query import Query, RetrievalResult
from src.models.workspace import Workspace


class _SessionContext:
    def __init__(self, session) -> None:
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


@pytest.mark.asyncio
async def test_phase_b_pipeline_ingests_large_document_as_parent_child_graph(db_session, monkeypatch) -> None:
    workspace_slug = f"project_affine_split_{uuid4().hex[:8]}"
    workspace = Workspace(
        id=uuid4(),
        slug=workspace_slug,
        name="AFFiNE",
        workspace_type=WorkspaceType.project_pack,
    )
    document = Document(
        id=uuid4(),
        workspace_id=workspace.id,
        title="Architecture Decision Record",
        file_name="adr.md",
        source_type="github",
        source_uri="https://example.test/adr",
        storage_bucket="docwise-documents",
        storage_key=f"{workspace.id}/adr/architecture-decision-record.md",
        content_type="text/markdown",
        file_size=80 * 1024,
        content_hash="phase-b-parent-hash",
        document_metadata=None,
        provenance={"source": "affine", "original_path": "docs/adr/architecture-decision-record.md"},
        parent_document_id=None,
        is_container=False,
        doc_type=DocType.tech_doc,
        status=DocumentStatus.pending,
        chunk_count=0,
        index_version=0,
    )
    db_session.add(workspace)
    db_session.add(document)
    await db_session.flush()

    async def fake_commit() -> None:
        await db_session.flush()

    large_markdown = (
        "# Context\n\n"
        + ("A" * 400 + "\n") * 100
        + "\n# Decisions\n\n"
        + ("B" * 400 + "\n") * 100
    ).encode("utf-8")

    async def fake_read_minio_object(_minio_client, _bucket: str, _key: str) -> bytes:
        return large_markdown

    async def fake_parse_document_bytes(file_bytes: bytes, file_name: str, content_type: str):
        from src.document.markdown_parser import parse_markdown

        return await parse_markdown(file_bytes, file_name, content_type)

    async def fake_embed_chunk_drafts(chunks):
        return [[0.0] * 2048 for _ in chunks]

    monkeypatch.setattr(db_session, "commit", fake_commit)
    monkeypatch.setattr(ingestion_module, "async_session_factory", lambda: _SessionContext(db_session))
    monkeypatch.setattr(ingestion_module, "Minio", lambda *args, **kwargs: object())
    monkeypatch.setattr(ingestion_module, "_read_minio_object", fake_read_minio_object)
    monkeypatch.setattr(ingestion_module, "parse_document_bytes", fake_parse_document_bytes)
    monkeypatch.setattr(ingestion_module, "_embed_chunk_drafts", fake_embed_chunk_drafts)

    result = await ingestion_module.ingest_document_by_id(document.id)

    parent = await db_session.get(Document, document.id)
    children = (
        await db_session.scalars(
            select(Document).where(Document.parent_document_id == document.id).order_by(Document.file_name)
        )
    ).all()
    child_chunks = (
        await db_session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id.in_([child.id for child in children]), DocumentChunk.is_active.is_(True))
            .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
        )
    ).all()

    assert result["status"] == "container"
    assert parent is not None
    assert parent.status == DocumentStatus.container
    assert parent.is_container is True
    assert parent.chunk_count == 0
    assert len(children) == 2
    assert all(child.parent_document_id == parent.id for child in children)
    assert all(child.storage_key == parent.storage_key for child in children)
    assert all(child.status == DocumentStatus.ready for child in children)
    assert child_chunks
    assert len(child_chunks) == result["chunk_count"]
    assert all(chunk.content_tsv is not None for chunk in child_chunks)


@pytest.mark.asyncio
async def test_phase_b_pipeline_preserves_historical_parent_chunks_with_retrieval_results(db_session, monkeypatch) -> None:
    workspace = Workspace(
        id=uuid4(),
        slug=f"project_affine_history_{uuid4().hex[:8]}",
        name="AFFiNE",
        workspace_type=WorkspaceType.project_pack,
    )
    document = Document(
        id=uuid4(),
        workspace_id=workspace.id,
        title="Legacy ADR",
        file_name="legacy-adr.md",
        source_type="github",
        source_uri="https://example.test/legacy-adr",
        storage_bucket="docwise-documents",
        storage_key=f"{workspace.id}/legacy/legacy-adr.md",
        content_type="text/markdown",
        file_size=80 * 1024,
        content_hash="legacy-parent-hash",
        document_metadata=None,
        provenance={"source": "affine", "original_path": "docs/legacy-adr.md"},
        parent_document_id=None,
        is_container=False,
        doc_type=DocType.tech_doc,
        status=DocumentStatus.ready,
        chunk_count=1,
        index_version=1,
    )
    legacy_chunk = DocumentChunk(
        id=uuid4(),
        document_id=document.id,
        workspace_id=workspace.id,
        chunk_uid="legacy-adr:context:old",
        chunk_index=0,
        content="legacy chunk",
        content_hash="legacy-chunk-hash",
        token_count=32,
        char_count=12,
        section_title="Context",
        section_path="Context",
        heading_level=1,
        page_number=None,
        start_char=0,
        end_char=12,
        source_anchor="context",
        doc_type=DocType.tech_doc,
        language=ChunkLanguage.en,
        chunk_metadata=None,
        embedding=[0.0] * 2048,
        content_tsv=None,
        embedding_model="text-embedding-v4",
        embedding_dim=2048,
        index_version=1,
        is_active=True,
    )
    query = Query(id=uuid4(), original_query="What changed?", refused=False, is_archived=False)
    run = AgentRun(
        id=uuid4(),
        query_id=query.id,
        turn_index=0,
        original_query=query.original_query,
        status=AgentRunStatus.succeeded,
    )
    retrieval = RetrievalResult(
        id=uuid4(),
        query_id=query.id,
        run_id=run.id,
        chunk_id=legacy_chunk.id,
        chunk_uid=legacy_chunk.chunk_uid,
        document_id=document.id,
        workspace_id=workspace.id,
        vector_score=0.5,
        retrieval_stage=RetrievalStage.vector,
    )
    db_session.add(workspace)
    db_session.add(document)
    db_session.add(legacy_chunk)
    db_session.add(query)
    await db_session.flush()
    db_session.add(run)
    await db_session.flush()
    db_session.add(retrieval)
    await db_session.flush()

    async def fake_commit() -> None:
        await db_session.flush()

    large_markdown = (
        "# Context\n\n"
        + ("A" * 400 + "\n") * 90
        + "\n# Decisions\n\n"
        + ("B" * 400 + "\n") * 90
    ).encode("utf-8")

    async def fake_read_minio_object(_minio_client, _bucket: str, _key: str) -> bytes:
        return large_markdown

    async def fake_parse_document_bytes(file_bytes: bytes, file_name: str, content_type: str):
        from src.document.markdown_parser import parse_markdown

        return await parse_markdown(file_bytes, file_name, content_type)

    async def fake_embed_chunk_drafts(chunks):
        return [[0.0] * 2048 for _ in chunks]

    monkeypatch.setattr(db_session, "commit", fake_commit)
    monkeypatch.setattr(ingestion_module, "async_session_factory", lambda: _SessionContext(db_session))
    monkeypatch.setattr(ingestion_module, "Minio", lambda *args, **kwargs: object())
    monkeypatch.setattr(ingestion_module, "_read_minio_object", fake_read_minio_object)
    monkeypatch.setattr(ingestion_module, "parse_document_bytes", fake_parse_document_bytes)
    monkeypatch.setattr(ingestion_module, "_embed_chunk_drafts", fake_embed_chunk_drafts)

    result = await ingestion_module.ingest_document_by_id(document.id)

    refreshed_parent = await db_session.get(Document, document.id)
    refreshed_legacy_chunk = await db_session.get(DocumentChunk, legacy_chunk.id)
    refreshed_retrieval = await db_session.get(RetrievalResult, retrieval.id)

    assert result["status"] == "container"
    assert refreshed_parent is not None
    assert refreshed_parent.status == DocumentStatus.container
    assert refreshed_legacy_chunk is not None
    assert refreshed_legacy_chunk.is_active is False
    assert refreshed_retrieval is not None
    assert refreshed_retrieval.chunk_id == legacy_chunk.id


@pytest.mark.asyncio
async def test_phase_b_pipeline_exports_chunk_index_json_with_active_chunk_count(db_session, monkeypatch, tmp_path: Path) -> None:
    workspace_slug = f"project_affine_export_{uuid4().hex[:8]}"
    workspace = Workspace(
        id=uuid4(),
        slug=workspace_slug,
        name="AFFiNE",
        workspace_type=WorkspaceType.project_pack,
    )
    parent = Document(
        id=uuid4(),
        workspace_id=workspace.id,
        title="Parent ADR",
        file_name="parent-adr.md",
        source_type="github",
        source_uri="https://example.test/adr",
        storage_bucket="docwise-documents",
        storage_key="project_affine/parent-adr.md",
        content_type="text/markdown",
        file_size=4096,
        content_hash="parent-doc-hash",
        document_metadata=None,
        provenance={"source": "affine", "original_path": "docs/adr/parent-adr.md"},
        parent_document_id=None,
        is_container=True,
        doc_type=DocType.tech_doc,
        status=DocumentStatus.container,
        chunk_count=0,
        index_version=0,
    )
    child = Document(
        id=uuid4(),
        workspace_id=workspace.id,
        title="Parent ADR - Context",
        file_name="parent-adr.md#context",
        source_type="github",
        source_uri="https://example.test/adr",
        storage_bucket="docwise-documents",
        storage_key="project_affine/parent-adr.md",
        content_type="text/markdown",
        file_size=2048,
        content_hash="child-doc-hash",
        document_metadata=None,
        provenance={"source": "affine", "original_path": "docs/adr/parent-adr.md#context"},
        parent_document_id=parent.id,
        is_container=False,
        doc_type=DocType.tech_doc,
        status=DocumentStatus.ready,
        chunk_count=2,
        index_version=1,
    )
    chunks = [
        DocumentChunk(
            id=uuid4(),
            document_id=child.id,
            workspace_id=workspace.id,
            chunk_uid=f"parent-adr:context:{index}",
            chunk_index=index,
            content=f"chunk-{index}",
            content_hash=f"chunk-hash-{index}",
            token_count=100 + index,
            char_count=7,
            section_title="Context",
            section_path="Context",
            heading_level=1,
            page_number=None,
            start_char=index * 10,
            end_char=index * 10 + 7,
            source_anchor="context",
            doc_type=DocType.tech_doc,
            language=ChunkLanguage.en,
            chunk_metadata=None,
            embedding=[0.0] * 2048,
            content_tsv=None,
            embedding_model="text-embedding-v4",
            embedding_dim=2048,
            index_version=1,
            is_active=True,
        )
        for index in range(2)
    ]
    db_session.add(workspace)
    db_session.add(parent)
    db_session.add(child)
    for chunk in chunks:
        db_session.add(chunk)
    await db_session.flush()

    monkeypatch.setattr(export_chunk_index, "async_session_factory", lambda: _SessionContext(db_session))
    output_path = tmp_path / "chunk_index.json"

    await export_chunk_index.export_chunk_index(
        output_path=output_path,
        output_format="json",
        workspace_slug=workspace.slug,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    db_count = int(
        await db_session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .join(Workspace, Workspace.id == Document.workspace_id)
            .where(DocumentChunk.is_active.is_(True), Workspace.slug == workspace.slug)
        )
        or 0
    )

    assert len(payload) == db_count
    assert {row["chunk_uid"] for row in payload} == {chunk.chunk_uid for chunk in chunks}
    assert all(row["workspace_slug"] == workspace.slug for row in payload)


@pytest.mark.asyncio
async def test_phase_b_pipeline_exports_chunk_index_csv_with_legacy_columns(db_session, monkeypatch, tmp_path: Path) -> None:
    workspace_slug = f"project_affine_csv_{uuid4().hex[:8]}"
    workspace = Workspace(
        id=uuid4(),
        slug=workspace_slug,
        name="AFFiNE",
        workspace_type=WorkspaceType.project_pack,
    )
    document = Document(
        id=uuid4(),
        workspace_id=workspace.id,
        title="CSV ADR",
        file_name="csv-adr.md",
        source_type="github",
        source_uri="https://example.test/csv-adr",
        storage_bucket="docwise-documents",
        storage_key="project_affine/csv-adr.md",
        content_type="text/markdown",
        file_size=1024,
        content_hash="csv-doc-hash",
        document_metadata=None,
        provenance={"source": "affine", "original_path": "docs/csv-adr.md"},
        parent_document_id=None,
        is_container=False,
        doc_type=DocType.tech_doc,
        status=DocumentStatus.ready,
        chunk_count=1,
        index_version=1,
    )
    chunk = DocumentChunk(
        id=uuid4(),
        document_id=document.id,
        workspace_id=workspace.id,
        chunk_uid="csv-adr:overview:0",
        chunk_index=0,
        content="csv chunk",
        content_hash="csv-chunk-hash",
        token_count=88,
        char_count=9,
        section_title="Overview",
        section_path="Overview",
        heading_level=1,
        page_number=None,
        start_char=0,
        end_char=9,
        source_anchor="overview",
        doc_type=DocType.tech_doc,
        language=ChunkLanguage.en,
        chunk_metadata=None,
        embedding=[0.0] * 2048,
        content_tsv=None,
        embedding_model="text-embedding-v4",
        embedding_dim=2048,
        index_version=1,
        is_active=True,
    )
    db_session.add(workspace)
    db_session.add(document)
    db_session.add(chunk)
    await db_session.flush()

    monkeypatch.setattr(export_chunk_index, "async_session_factory", lambda: _SessionContext(db_session))
    output_path = tmp_path / "chunk_index.csv"

    await export_chunk_index.export_chunk_index(
        output_path=output_path,
        output_format="csv",
        workspace_slug=workspace.slug,
    )

    with output_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))

    assert rows[0] == export_chunk_index.CSV_HEADERS
    assert rows[1] == [
        chunk.chunk_uid,
        str(document.id),
        str(document.workspace_id),
        "Overview",
        "Overview",
        "tech_doc",
        "en",
        "88",
    ]
