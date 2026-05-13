from __future__ import annotations

import csv
import json
from pathlib import Path
from uuid import uuid4

import pytest

import scripts.export_chunk_index as export_chunk_index
from src.models.base import ChunkLanguage, DocType, WorkspaceType
from src.models.document import Document, DocumentChunk
from src.models.workspace import Workspace


def _sample_rows() -> list[tuple[DocumentChunk, Document, Workspace]]:
    workspace = Workspace(
        id=uuid4(),
        slug="project_affine",
        name="AFFiNE",
        workspace_type=WorkspaceType.project_pack,
    )
    document = Document(
        id=uuid4(),
        workspace_id=workspace.id,
        title="Descriptor Format",
        file_name="descriptor-format.md",
        source_type="github",
        source_uri="https://example.test/repo",
        storage_bucket="docwise-documents",
        storage_key="project_affine/doc/descriptor-format.md",
        content_type="text/markdown",
        file_size=2048,
        content_hash="hash-1",
        document_metadata=None,
        provenance={
            "source": "affine",
            "commit_sha": "abc1234",
            "original_path": "docs/features/descriptor-format.md",
            "license": "MIT",
            "original_format": "md",
            "normalizer": "passthrough",
        },
        parent_document_id=None,
        is_container=False,
        doc_type=DocType.tech_doc,
        chunk_count=1,
        index_version=1,
    )
    chunk = DocumentChunk(
        id=uuid4(),
        document_id=document.id,
        workspace_id=workspace.id,
        chunk_uid="descriptor-format:overview:abc123",
        chunk_index=0,
        content="content",
        content_hash="chunk-hash",
        token_count=412,
        char_count=7,
        section_title="Descriptor Format",
        section_path="features > software-catalog > descriptor-format",
        heading_level=2,
        page_number=None,
        start_char=0,
        end_char=7,
        source_anchor="descriptor-format",
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
    return [(chunk, document, workspace)]


@pytest.mark.asyncio
async def test_export_chunk_index_json_schema_completeness(monkeypatch, tmp_path: Path) -> None:
    rows = _sample_rows()

    async def fake_load_active_chunks(workspace_slug: str | None = None):
        assert workspace_slug is None
        return rows

    monkeypatch.setattr(export_chunk_index, "_load_active_chunks", fake_load_active_chunks)
    output_path = tmp_path / "chunk_index.json"

    await export_chunk_index.export_chunk_index(output_path=output_path, output_format="json")

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert len(payload) == 1
    assert payload[0] == {
        "chunk_uid": "descriptor-format:overview:abc123",
        "chunk_id": str(rows[0][0].id),
        "document_id": str(rows[0][1].id),
        "document_title": "Descriptor Format",
        "workspace_slug": "project_affine",
        "section_path": "features > software-catalog > descriptor-format",
        "doc_type": "tech_doc",
        "language": "en",
        "token_count": 412,
        "is_active": True,
        "parent_document_id": None,
        "provenance": {
            "source": "affine",
            "commit_sha": "abc1234",
            "original_path": "docs/features/descriptor-format.md",
            "license": "MIT",
            "original_format": "md",
            "normalizer": "passthrough",
        },
    }


@pytest.mark.asyncio
async def test_export_chunk_index_csv_keeps_legacy_column_order(monkeypatch, tmp_path: Path) -> None:
    rows = _sample_rows()

    async def fake_load_active_chunks(workspace_slug: str | None = None):
        assert workspace_slug is None
        return rows

    monkeypatch.setattr(export_chunk_index, "_load_active_chunks", fake_load_active_chunks)
    output_path = tmp_path / "chunk_index.csv"

    await export_chunk_index.export_chunk_index(output_path=output_path, output_format="csv")

    with output_path.open("r", encoding="utf-8", newline="") as handle:
        reader = list(csv.reader(handle))

    assert reader[0] == export_chunk_index.CSV_HEADERS
    assert reader[1] == [
        rows[0][0].chunk_uid,
        str(rows[0][1].id),
        str(rows[0][1].workspace_id),
        rows[0][0].section_title or "",
        rows[0][0].section_path or "",
        rows[0][1].doc_type.value,
        rows[0][0].language.value,
        str(rows[0][0].token_count),
    ]


@pytest.mark.asyncio
async def test_export_chunk_index_respects_workspace_filter(monkeypatch, tmp_path: Path) -> None:
    seen_workspace_filters: list[str | None] = []

    async def fake_load_active_chunks(workspace_slug: str | None = None):
        seen_workspace_filters.append(workspace_slug)
        return _sample_rows() if workspace_slug == "project_affine" else []

    monkeypatch.setattr(export_chunk_index, "_load_active_chunks", fake_load_active_chunks)
    output_path = tmp_path / "chunk_index.json"

    await export_chunk_index.export_chunk_index(
        output_path=output_path,
        output_format="json",
        workspace_slug="project_affine",
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert seen_workspace_filters == ["project_affine"]
    assert len(payload) == 1
    assert payload[0]["workspace_slug"] == "project_affine"
