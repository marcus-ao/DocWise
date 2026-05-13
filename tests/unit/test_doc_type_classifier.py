from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

import src.document.ingestion as ingestion_module
from src.document.doc_type_classifier import classify_doc_type
from src.document.ingestion import submit_document_for_ingestion
from src.document.markdown_parser import compute_section_path_fallback, extract_frontmatter, parse_markdown
from src.models.base import DocType, WorkspaceType
from src.models.workspace import Workspace


@pytest.mark.parametrize(
    ("relative_path", "expected"),
    [
        ("ops/runbook-service.md", DocType.runbook),
        ("public_tech/incident-response.md", DocType.runbook),
        ("manual/sop/network-reset.md", DocType.runbook),
        ("team/runbook.redis.md", DocType.runbook),
        ("guide/troubleshooting/api-gateway.md", DocType.sop),
        ("incidents/outage-2026.md", DocType.sop),
        ("notes/not-a-troubleshooter.md", DocType.sop),
        ("support/troubleshooting_worker.md", DocType.sop),
        ("reference/openapi.json.md", DocType.api_doc),
        ("docs/swagger/auth.md", DocType.api_doc),
        ("apis/reference/user-create.md", DocType.api_doc),
        ("backend/api/overview.md", DocType.api_doc),
        ("public_tech/fastapi/tutorial-01.md", DocType.tech_doc),
        ("langgraph/concepts/state-machine.md", DocType.tech_doc),
        ("misc/architecture-notes.md", DocType.tech_doc),
    ],
)
def test_classify_doc_type_matches_expected_priority(relative_path: str, expected: DocType) -> None:
    assert classify_doc_type(relative_path) is expected


def test_extract_frontmatter_success() -> None:
    frontmatter, body = extract_frontmatter("---\ntitle: FastAPI Title\ntags:\n  - api\n---\n# Body\n")

    assert frontmatter["title"] == "FastAPI Title"
    assert frontmatter["tags"] == ["api"]
    assert body == "# Body\n"


def test_extract_frontmatter_yaml_error_keeps_original_text() -> None:
    original = "---\ntitle: [bad\n---\nBody\n"

    frontmatter, body = extract_frontmatter(original)

    assert frontmatter == {}
    assert body == original


def test_compute_section_path_fallback_uses_parent_dir_and_stem() -> None:
    assert compute_section_path_fallback(Path("public_tech/fastapi/tutorial-01.md")) == "fastapi > tutorial-01"


async def test_parse_markdown_uses_frontmatter_title_and_section_fallback() -> None:
    parsed = await parse_markdown(
        b"---\ntitle: API Guide\n---\nRequest body details.\n",
        "public_tech/fastapi/tutorial-01.md",
        "text/markdown",
    )

    assert parsed.title == "API Guide"
    assert parsed.metadata["frontmatter"]["title"] == "API Guide"
    paragraph = next(block for block in parsed.blocks if block.block_type == "paragraph")
    assert paragraph.section_path == "fastapi > tutorial-01"


async def test_submit_document_for_ingestion_classifies_doc_type_when_not_explicit(monkeypatch) -> None:
    workspace = Workspace(
        id=uuid4(),
        slug="public_tech",
        name="Public Tech",
        workspace_type=WorkspaceType.public_tech,
    )

    class FakeSession:
        def __init__(self):
            self.added = []

        async def scalar(self, stmt):
            return workspace

        def add(self, obj):
            self.added.append(obj)

        async def flush(self):
            for obj in self.added:
                if getattr(obj, "id", None) is None:
                    obj.id = uuid4()

        async def commit(self):
            return None

        async def rollback(self):
            return None

    class FakeMinio:
        def __init__(self):
            self.buckets = set()

        def bucket_exists(self, bucket):
            return bucket in self.buckets

        def make_bucket(self, bucket):
            self.buckets.add(bucket)

        def put_object(self, bucket, key, data, length, content_type=None):
            data.read()
            return None

    async def fake_find_existing(session, workspace_id, file_hash):
        return None, None

    monkeypatch.setattr(ingestion_module, "_find_existing_document", fake_find_existing)

    session = FakeSession()
    result = await submit_document_for_ingestion(
        session=session,
        redis=None,
        minio_client=FakeMinio(),
        file_bytes=b"# Runbook",
        file_name="incident-response.md",
        workspace_slug="public_tech",
        provenance={"original_path": "public_tech/runbooks/incident-response.md"},
        enqueue=False,
    )

    created_document = next(obj for obj in session.added if getattr(obj, "__tablename__", "") == "documents")
    assert created_document.doc_type is DocType.runbook
    assert created_document.provenance["original_path"] == "public_tech/runbooks/incident-response.md"
    assert result["existing"] is False
