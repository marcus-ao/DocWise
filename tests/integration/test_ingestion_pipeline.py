import sys
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest

import scripts.download_docs as download_docs
import scripts.ingest_docs as ingest_docs
import src.document.ingestion as ingestion_module
import src.tasks.jobs as jobs_module
from src.document.ingestion import _metadata_kwargs, sanitize_filename, submit_document_for_ingestion
from src.models.base import DocumentStatus, JobStatus, WorkspaceType
from src.models.document import DocumentChunk
from src.models.workspace import Workspace
from src.tasks.helpers import update_job_progress, update_job_status
from src.tasks.worker import WorkerSettings


def test_worker_settings_exposes_required_jobs():
    function_names = {function.__name__ for function in WorkerSettings.functions}

    assert function_names == {"process_ingest_document", "process_reindex", "process_eval_run"}
    assert WorkerSettings.max_jobs == 5


def test_sanitize_filename_removes_path_segments_and_limits_length():
    unsafe = "../secret\\airflow task failure?.md"

    safe = sanitize_filename(unsafe)

    assert ".." not in safe
    assert "\\" not in safe
    assert "/" not in safe
    assert safe.endswith(".md")
    assert len(safe) <= 255


def test_chunk_metadata_uses_current_sqlalchemy_attribute_name():
    kwargs = _metadata_kwargs({"contains_code": True})

    if "metadata" in DocumentChunk.__mapper__.attrs.keys():
        assert kwargs == {"metadata": {"contains_code": True}}
    else:
        assert kwargs == {"chunk_metadata": {"contains_code": True}}


async def test_job_helpers_update_progress_and_status_transitions():
    job = SimpleNamespace(
        progress=None,
        status=JobStatus.queued,
        error_message=None,
        result_json=None,
        started_at=None,
        finished_at=None,
        updated_at=None,
    )

    class FakeSession:
        def __init__(self):
            self.flush_count = 0

        async def scalar(self, stmt):
            return job

        async def flush(self):
            self.flush_count += 1

    session = FakeSession()

    await update_job_progress(session, uuid4(), "chunking", 150, 2, 3, "Chunking")
    await update_job_status(session, uuid4(), JobStatus.running)
    await update_job_status(session, uuid4(), JobStatus.succeeded, result_json={"ok": True})

    assert job.progress == {"stage": "chunking", "percent": 100, "current": 2, "total": 3, "message": "Chunking"}
    assert job.status == JobStatus.succeeded
    assert job.started_at is not None
    assert job.finished_at is not None
    assert job.result_json == {"ok": True}
    assert session.flush_count == 3


async def test_job_entrypoints_delegate_to_pipeline_functions(monkeypatch):
    calls: list[tuple[str, str]] = []

    async def fake_ingest(job_id):
        calls.append(("ingest", job_id))
        return {"job_id": job_id}

    async def fake_reindex(job_id):
        calls.append(("reindex", job_id))
        return {"job_id": job_id}

    fake_eval_module = ModuleType("src.observability.evaluator")

    async def fake_run_eval(job_id):
        calls.append(("eval", job_id))
        return {"job_id": job_id}

    fake_eval_module.run_eval = fake_run_eval

    monkeypatch.setattr(jobs_module, "ingest_document_by_job_id", fake_ingest)
    monkeypatch.setattr(jobs_module, "reindex_document_by_job_id", fake_reindex)
    monkeypatch.setitem(sys.modules, "src.observability.evaluator", fake_eval_module)

    assert await jobs_module.process_ingest_document({}, "job-1") == {"job_id": "job-1"}
    assert await jobs_module.process_reindex({}, "job-2") == {"job_id": "job-2"}
    assert await jobs_module.process_eval_run({}, "job-3") == {"job_id": "job-3"}
    assert calls == [("ingest", "job-1"), ("reindex", "job-2"), ("eval", "job-3")]


async def test_submit_document_removes_minio_object_if_db_commit_fails(monkeypatch):
    workspace = Workspace(
        id=uuid4(),
        slug="public_tech",
        name="Public Tech",
        workspace_type=WorkspaceType.public_tech,
    )

    class FakeSession:
        def __init__(self):
            self.added = []
            self.rollback_called = False

        async def scalar(self, stmt):
            return workspace

        def add(self, obj):
            self.added.append(obj)

        async def flush(self):
            for obj in self.added:
                if getattr(obj, "id", None) is None:
                    obj.id = uuid4()

        async def commit(self):
            raise RuntimeError("db commit failed")

        async def rollback(self):
            self.rollback_called = True

    class FakeMinio:
        def __init__(self):
            self.buckets = set()
            self.put_keys = []
            self.removed_keys = []

        def bucket_exists(self, bucket):
            return bucket in self.buckets

        def make_bucket(self, bucket):
            self.buckets.add(bucket)

        def put_object(self, bucket, key, data, length, content_type=None):
            self.put_keys.append((bucket, key, length, content_type))
            assert data.read() == b"# Runbook"

        def remove_object(self, bucket, key):
            self.removed_keys.append((bucket, key))

    async def fake_find_existing(session, workspace_id, file_hash):
        return None, None

    session = FakeSession()
    minio = FakeMinio()
    monkeypatch.setattr(ingestion_module, "_find_existing_document", fake_find_existing)

    with pytest.raises(RuntimeError, match="db commit failed"):
        await submit_document_for_ingestion(
            session=session,
            redis=None,
            minio_client=minio,
            file_bytes=b"# Runbook",
            file_name="runbook.md",
            workspace_slug="public_tech",
            enqueue=False,
        )

    assert session.rollback_called is True
    assert "docwise-documents" in minio.buckets
    assert minio.put_keys
    assert minio.removed_keys == [(minio.put_keys[0][0], minio.put_keys[0][1])]


async def test_submit_document_restores_missing_minio_object_for_existing_document(monkeypatch):
    workspace = Workspace(
        id=uuid4(),
        slug="public_tech",
        name="Public Tech",
        workspace_type=WorkspaceType.public_tech,
    )
    existing_document = SimpleNamespace(
        id=uuid4(),
        workspace_id=workspace.id,
        storage_bucket="docwise-documents",
        storage_key="workspace/document/runbook.md",
        content_type="text/markdown",
        status=SimpleNamespace(value="ready"),
    )
    existing_job = SimpleNamespace(id=uuid4())

    class FakeSession:
        async def scalar(self, stmt):
            return workspace

    class FakeMinio:
        def __init__(self):
            self.buckets = set()
            self.put_keys = []

        def bucket_exists(self, bucket):
            return bucket in self.buckets

        def make_bucket(self, bucket):
            self.buckets.add(bucket)

        def stat_object(self, bucket, key):
            raise RuntimeError("missing object")

        def put_object(self, bucket, key, data, length, content_type=None):
            self.put_keys.append((bucket, key, data.read(), length, content_type))

    async def fake_find_existing(session, workspace_id, file_hash):
        return existing_document, existing_job

    monkeypatch.setattr(ingestion_module, "_find_existing_document", fake_find_existing)

    minio = FakeMinio()
    result = await submit_document_for_ingestion(
        session=FakeSession(),
        redis=None,
        minio_client=minio,
        file_bytes=b"# Runbook",
        file_name="runbook.md",
        workspace_slug="public_tech",
        content_type="text/markdown",
        enqueue=False,
    )

    assert result["document_id"] == existing_document.id
    assert result["status"] == "ready"
    assert "docwise-documents" in minio.buckets
    assert minio.put_keys == [
        ("docwise-documents", "workspace/document/runbook.md", b"# Runbook", 9, "text/markdown")
    ]


async def test_submit_existing_pending_document_reenqueues_finished_arq_job(monkeypatch):
    workspace = Workspace(
        id=uuid4(),
        slug="public_tech",
        name="Public Tech",
        workspace_type=WorkspaceType.public_tech,
    )
    existing_document = SimpleNamespace(
        id=uuid4(),
        workspace_id=workspace.id,
        storage_bucket="docwise-documents",
        storage_key="workspace/document/runbook.md",
        content_type="text/markdown",
        content_hash="hash",
        status=DocumentStatus.pending,
        error_message="old failure",
    )
    existing_job = SimpleNamespace(
        id=uuid4(),
        status=JobStatus.queued,
        arq_job_id="old-arq-job",
        error_message="old failure",
        result_json={"ok": False},
        started_at=object(),
        finished_at=object(),
        progress=None,
    )

    class FakeSession:
        def __init__(self):
            self.commit_count = 0

        async def scalar(self, stmt):
            return workspace

        async def commit(self):
            self.commit_count += 1

    class FakeRedis:
        async def exists(self, key):
            assert key == "arq:result:old-arq-job"
            return 1

    class FakeMinio:
        def stat_object(self, bucket, key):
            return object()

    async def fake_find_existing(session, workspace_id, file_hash):
        return existing_document, existing_job

    async def fake_enqueue(job_id):
        assert job_id == existing_job.id
        return "new-arq-job"

    session = FakeSession()
    monkeypatch.setattr(ingestion_module, "_find_existing_document", fake_find_existing)
    monkeypatch.setattr(ingestion_module, "enqueue_ingest_job", fake_enqueue)

    result = await submit_document_for_ingestion(
        session=session,
        redis=FakeRedis(),
        minio_client=FakeMinio(),
        file_bytes=b"# Runbook",
        file_name="runbook.md",
        workspace_slug="public_tech",
        content_type="text/markdown",
        enqueue=True,
    )

    assert result["existing"] is True
    assert result["document_id"] == existing_document.id
    assert result["job_id"] == existing_job.id
    assert result["status"] == "queued"
    assert existing_document.status == DocumentStatus.pending
    assert existing_document.error_message is None
    assert existing_job.status == JobStatus.queued
    assert existing_job.arq_job_id == "new-arq-job"
    assert existing_job.error_message is None
    assert existing_job.result_json is None
    assert existing_job.started_at is None
    assert existing_job.finished_at is None
    assert existing_job.progress == {
        "stage": "queued",
        "percent": 0,
        "current": 0,
        "total": 1,
        "message": "Queued document ingestion",
    }
    assert session.commit_count == 1


async def test_ingest_path_respects_enqueue_sync_and_existing_modes(monkeypatch, tmp_path):
    path = tmp_path / "doc.md"
    path.write_text("# Doc", encoding="utf-8")
    submitted_enqueue_flags: list[bool] = []
    ingested_jobs: list[tuple[str, str]] = []

    class FakeSessionContext:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeRedis:
        async def aclose(self):
            return None

    async def fake_submit_document_for_ingestion(**kwargs):
        submitted_enqueue_flags.append(kwargs["enqueue"])
        return {"document_id": "doc-1", "job_id": "job-1", "status": "queued", "existing": False}

    async def fake_ingest_document_by_id(document_id, job_id):
        ingested_jobs.append((document_id, job_id))
        return {"status": "ready"}

    monkeypatch.setattr(ingest_docs, "Minio", lambda *args, **kwargs: object())
    monkeypatch.setattr(ingest_docs, "get_redis_client", lambda: FakeRedis())
    monkeypatch.setattr(ingest_docs, "async_session_factory", lambda: FakeSessionContext())
    monkeypatch.setattr(ingest_docs, "submit_document_for_ingestion", fake_submit_document_for_ingestion)
    monkeypatch.setattr(ingest_docs, "ingest_document_by_id", fake_ingest_document_by_id)

    sync_result = await ingest_docs.ingest_path(path, "public_tech", enqueue=False)
    enqueue_result = await ingest_docs.ingest_path(path, "public_tech", enqueue=True)

    async def fake_existing_submit_document_for_ingestion(**kwargs):
        submitted_enqueue_flags.append(kwargs["enqueue"])
        return {"document_id": "doc-1", "job_id": "job-1", "status": "ready", "existing": True}

    monkeypatch.setattr(ingest_docs, "submit_document_for_ingestion", fake_existing_submit_document_for_ingestion)
    existing_result = await ingest_docs.ingest_path(path, "public_tech", enqueue=False)

    assert submitted_enqueue_flags == [False, True, False]
    assert ingested_jobs == [("doc-1", "job-1")]
    assert sync_result["status"] == "ready"
    assert enqueue_result["status"] == "queued"
    assert existing_result["status"] == "ready"


def test_download_docs_is_repeatable_sample_generator(monkeypatch, tmp_path):
    target = tmp_path / "raw" / "sample.md"
    monkeypatch.setattr(download_docs, "SAMPLES", {str(target): "# Sample\n"})

    download_docs.main()
    download_docs.main()

    assert target.read_text(encoding="utf-8") == "# Sample\n"
