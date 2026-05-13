"""Phase B Migration 007 round-trip integration test.

Relocated from tests/unit/ per Phase B review MEDIUM #5: these tests shell out to
``alembic`` and talk to a real PostgreSQL instance, which makes them integration
(not unit) tests. They auto-skip when the configured database is unreachable so
that CI environments without Postgres do not fail.
"""
from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.config.settings import settings
from src.models.base import DocType, DocumentStatus, WorkspaceType
from src.models.document import Document
from src.models.workspace import Workspace

REPO_ROOT = Path(__file__).resolve().parents[2]


def _db_reachable() -> bool:
    """Return True when the configured Postgres host:port accepts TCP connections."""
    host = settings.postgres_host or "localhost"
    port = int(settings.postgres_port or 5432)
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _db_reachable(),
    reason="Postgres not reachable; migration round-trip test requires a real DB",
)


def _run_alembic(*args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic/alembic.ini", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_phase_b_migration_round_trip() -> None:
    """alembic downgrade 006 → upgrade head should complete without error."""
    _run_alembic("downgrade", "006")
    try:
        _run_alembic("upgrade", "head")
    finally:
        _run_alembic("upgrade", "head")


@pytest.mark.asyncio
async def test_phase_b_document_fields_round_trip() -> None:
    """Document ORM can round-trip the new 007 columns and DocumentStatus.container."""
    _run_alembic("upgrade", "head")

    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    workspace_id = uuid4()
    try:
        async with session_factory() as session:
            workspace = Workspace(
                id=workspace_id,
                slug=f"phase-b-{workspace_id.hex[:8]}",
                name="Phase B Test Workspace",
                workspace_type=WorkspaceType.public_tech,
            )
            session.add(workspace)
            await session.flush()

            parent = Document(
                workspace_id=workspace.id,
                title="Parent Container",
                file_name="parent.md",
                source_type="upload",
                source_uri=None,
                storage_bucket="docwise-documents",
                storage_key=f"{workspace.id}/parent.md",
                content_type="text/markdown",
                file_size=12,
                content_hash=f"parent-{workspace.id.hex}",
                document_metadata={"frontmatter": {"title": "Parent Container"}},
                provenance={"source": "unit_test", "original_format": "md"},
                doc_type=DocType.tech_doc,
                status=DocumentStatus.container,
                is_container=True,
                chunk_count=0,
                index_version=0,
            )
            session.add(parent)
            await session.flush()

            child = Document(
                workspace_id=workspace.id,
                title="Child Document",
                file_name="child.md",
                source_type="upload",
                source_uri=None,
                storage_bucket="docwise-documents",
                storage_key=f"{workspace.id}/child.md",
                content_type="text/markdown",
                file_size=24,
                content_hash=f"child-{workspace.id.hex}",
                document_metadata={"frontmatter": {"title": "Child Document"}},
                provenance={"source": "unit_test", "original_path": "docs/child.md"},
                parent_document_id=parent.id,
                doc_type=DocType.runbook,
                status=DocumentStatus.ready,
                is_container=False,
                chunk_count=1,
                index_version=1,
            )
            session.add(child)
            await session.commit()

            fetched_parent = await session.scalar(select(Document).where(Document.id == parent.id))
            fetched_child = await session.scalar(select(Document).where(Document.id == child.id))

            assert fetched_parent is not None
            assert fetched_parent.status is DocumentStatus.container
            assert fetched_parent.is_container is True
            assert fetched_parent.document_metadata["frontmatter"]["title"] == "Parent Container"

            assert fetched_child is not None
            assert fetched_child.parent_document_id == parent.id
            assert fetched_child.provenance["original_path"] == "docs/child.md"
            assert fetched_child.document_metadata["frontmatter"]["title"] == "Child Document"

            await session.execute(delete(Document).where(Document.id.in_([parent.id, child.id])))
            await session.execute(delete(Workspace).where(Workspace.id == workspace.id))
            await session.commit()
    finally:
        await engine.dispose()
