"""Integration tests for Agent D API routers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from src.api import deps
from src.api.citations import citations_from_final
from src.api.routers import admin, agent, chat, documents, eval
from src.frontend import api_client
from src.models.base import DocType, DocumentStatus, JobStatus
from src.models.document import Document
from src.models.eval import EvalResult


class FakeDb:
    def add(self, item: object) -> None:
        self.item = item

    async def commit(self) -> None:
        return None

    async def refresh(self, item: object) -> None:
        if getattr(item, "id", None) is None:
            item.id = uuid4()

    async def get(self, model: object, key: object) -> None:
        return None


async def fake_db() -> AsyncIterator[FakeDb]:
    yield FakeDb()


async def fake_redis() -> object:
    return object()


def fake_minio() -> object:
    return object()


async def fake_auth() -> None:
    return None


def _sse_events(body: str) -> list[str]:
    return [line.removeprefix("event: ") for line in body.splitlines() if line.startswith("event: ")]


def test_persisted_final_citations_preserve_rich_fields() -> None:
    chunk_id = uuid4()
    document_id = uuid4()

    citations = citations_from_final(
        [
            {
                "chunk_id": str(chunk_id),
                "chunk_uid": "doc:section:abc123",
                "document_id": str(document_id),
                "document_title": "Guide",
                "section_path": "Troubleshooting",
                "page_number": 3,
                "score": 0.91,
                "quote": "Check scheduler logs.",
            }
        ]
    )

    assert citations[0].chunk_id == chunk_id
    assert citations[0].document_id == document_id
    assert citations[0].document_title == "Guide"
    assert citations[0].quote == "Check scheduler logs."


@pytest.fixture
def app() -> FastAPI:
    test_app = FastAPI()
    for router in [documents.router, chat.router, agent.router, eval.router, admin.router]:
        test_app.include_router(router, prefix="/api/v1")
    test_app.dependency_overrides[deps.get_db] = fake_db
    test_app.dependency_overrides[deps.get_redis] = fake_redis
    test_app.dependency_overrides[deps.get_minio] = fake_minio
    test_app.dependency_overrides[deps.optional_admin_auth] = fake_auth
    return test_app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


def test_agent_d_routers_register_twenty_endpoints(app: FastAPI) -> None:
    paths = {
        (
            next(iter(methods)) if len(methods) == 1 else tuple(sorted(methods)),
            path,
        )
        for route in app.routes
        for methods in [getattr(route, "methods", set())]
        for path in [getattr(route, "path", "")]
        if methods
    }
    api_paths = [path for _, path in paths if path.startswith("/api/v1")]
    assert len(api_paths) >= 20
    assert "/api/v1/chat/stream" in api_paths
    assert "/api/v1/chat/history" in api_paths
    assert "/api/v1/documents" in api_paths
    assert "/api/v1/documents/upload" in api_paths
    assert "/api/v1/admin/index-status" in api_paths


def test_admin_bad_cases_filter_requires_non_empty_bad_case_types() -> None:
    statement = select(EvalResult).where(*admin._non_empty_bad_case_filter())
    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert "bad_case_types IS NOT NULL" in compiled
    assert "jsonb_array_length" in compiled


@pytest.mark.asyncio
async def test_upload_document_returns_contract_response(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    document_id = uuid4()
    job_id = uuid4()

    async def fake_create_upload_job(**kwargs: object) -> dict[str, object]:
        return {"document_id": document_id, "job_id": job_id, "status": "queued"}

    monkeypatch.setattr(documents, "_create_upload_job", fake_create_upload_job)
    response = await client.post(
        "/api/v1/documents/upload",
        data={"workspace_slug": "public_tech", "doc_type": "tech_doc"},
        files={"file": ("guide.md", b"# Guide", "text/markdown")},
    )
    assert response.status_code == 202
    assert response.json() == {"document_id": str(document_id), "job_id": str(job_id), "status": "queued"}


@pytest.mark.asyncio
async def test_upload_document_duplicate_without_job_returns_conflict(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_create_upload_job(**kwargs: object) -> dict[str, object]:
        return {"document_id": uuid4(), "job_id": None, "status": "ready"}

    monkeypatch.setattr(documents, "_create_upload_job", fake_create_upload_job)
    response = await client.post(
        "/api/v1/documents/upload",
        data={"workspace_slug": "public_tech", "doc_type": "tech_doc"},
        files={"file": ("guide.md", b"# Guide", "text/markdown")},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_reindex_document_enqueues_worker_job(monkeypatch: pytest.MonkeyPatch) -> None:
    document_id = uuid4()
    workspace_id = uuid4()
    document = Document(
        id=document_id,
        workspace_id=workspace_id,
        title="Guide",
        file_name="guide.md",
        source_type="upload",
        storage_bucket="docwise-documents",
        storage_key="key",
        content_type="text/markdown",
        file_size=10,
        content_hash="hash",
        doc_type=DocType.tech_doc,
        status=DocumentStatus.ready,
        chunk_count=1,
        index_version=2,
    )

    class FakeSession:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.commit_count = 0

        async def get(self, model: object, key: object) -> object:
            return document if key == document_id else None

        async def scalar(self, stmt: object) -> object | None:
            return None

        def add(self, item: object) -> None:
            self.added.append(item)

        async def commit(self) -> None:
            self.commit_count += 1

        async def refresh(self, item: object) -> None:
            if getattr(item, "id", None) is None:
                item.id = uuid4()
            if getattr(item, "created_at", None) is None:
                item.created_at = datetime.now(UTC)
            if getattr(item, "retry_count", None) is None:
                item.retry_count = 0

    enqueued: list[object] = []

    async def fake_enqueue(job_id: object) -> str:
        enqueued.append(job_id)
        return "arq-job-1"

    session = FakeSession()
    monkeypatch.setattr(documents, "enqueue_reindex_job", fake_enqueue)

    response = await documents.reindex_document(session, document_id, object(), None)

    assert response.status == "queued"
    assert response.job_type == "reindex_document"
    assert enqueued == [response.id]
    assert session.added[0].arq_job_id == "arq-job-1"


@pytest.mark.asyncio
async def test_reindex_document_reenqueues_stale_active_job(monkeypatch: pytest.MonkeyPatch) -> None:
    document_id = uuid4()
    document = make_document(document_id)
    existing_job = SimpleNamespace(
        id=uuid4(),
        job_type="reindex_document",
        status=JobStatus.queued,
        arq_job_id="old-arq-job",
        progress={"stage": "queued", "percent": 0, "current": 0, "total": 1, "message": "Queued reindex"},
        error_message="old failure",
        result_json={"ok": False},
        retry_count=0,
        started_at=object(),
        finished_at=object(),
        created_at=datetime.now(UTC),
    )

    class FakeSession:
        def __init__(self) -> None:
            self.commit_count = 0

        async def get(self, model: object, key: object) -> object:
            return document if key == document_id else None

        async def scalar(self, stmt: object) -> object | None:
            return existing_job

        async def commit(self) -> None:
            self.commit_count += 1

        async def refresh(self, item: object) -> None:
            return None

    class FakeRedis:
        async def exists(self, key: str) -> int:
            assert key == "arq:result:old-arq-job"
            return 1

    async def fake_enqueue(job_id: object) -> str:
        assert job_id == existing_job.id
        return "new-arq-job"

    session = FakeSession()
    monkeypatch.setattr(documents, "enqueue_reindex_job", fake_enqueue)

    response = await documents.reindex_document(session, document_id, FakeRedis(), None)

    assert response.status == "queued"
    assert existing_job.arq_job_id == "new-arq-job"
    assert existing_job.error_message is None
    assert existing_job.result_json is None
    assert existing_job.started_at is None
    assert existing_job.finished_at is None
    assert session.commit_count == 1


class FakeDeleteSession:
    def __init__(self, document: Document, rowcounts: list[int]) -> None:
        self.document = document
        self.rowcounts = rowcounts
        self.execute_count = 0
        self.commit_count = 0

    async def get(self, model: object, key: object) -> object:
        return self.document

    async def execute(self, stmt: object) -> object:
        rowcount = self.rowcounts[self.execute_count]
        self.execute_count += 1
        return SimpleNamespace(rowcount=rowcount)

    async def commit(self) -> None:
        self.commit_count += 1


def make_document(document_id: object | None = None) -> Document:
    return Document(
        id=document_id or uuid4(),
        workspace_id=uuid4(),
        title="Guide",
        file_name="guide.md",
        source_type="upload",
        storage_bucket="docwise-documents",
        storage_key="workspace/document/guide.md",
        content_type="text/markdown",
        file_size=10,
        content_hash="hash",
        doc_type=DocType.tech_doc,
        status=DocumentStatus.ready,
        chunk_count=1,
        index_version=1,
    )


@pytest.mark.asyncio
async def test_purge_document_removes_database_rows_and_storage_object() -> None:
    document_id = uuid4()
    session = FakeDeleteSession(make_document(document_id), [0, 1, 1, 1])

    class FakeMinio:
        def __init__(self) -> None:
            self.removed: list[tuple[str, str]] = []

        def remove_object(self, bucket: str, key: str) -> None:
            self.removed.append((bucket, key))

    minio = FakeMinio()

    response = await documents.purge_document(session, minio, document_id, None)

    assert response.mode == "record_and_storage"
    assert response.record_deleted is True
    assert response.storage_object_deleted is True
    assert response.warning is None
    assert minio.removed == [("docwise-documents", "workspace/document/guide.md")]
    assert session.execute_count == 4
    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_map_langgraph_events_matches_sse_contract() -> None:
    route = await chat.map_langgraph_event_to_sse(
        {
            "event": "on_chain_end",
            "name": "query_router",
            "data": {
                "output": {
                    "route": "troubleshooting",
                    "route_confidence": 0.92,
                    "workspace_policy": "selected_project_plus_public",
                    "workspace_ids": ["workspace-1"],
                    "selected_project": "data-platform",
                }
            },
        }
    )
    assert route is not None
    assert route.startswith("event: route\n")
    assert '"workspace_policy": "selected_project_plus_public"' in route

    token = await chat.map_langgraph_event_to_sse(
        {"event": "on_chat_model_stream", "name": "answer_generator", "data": {"chunk": {"content": "鏍规嵁"}}}
    )
    assert token == 'event: token\ndata: {"content": "鏍规嵁"}\n\n'


@pytest.mark.asyncio
async def test_tool_result_emits_latest_round_only() -> None:
    mapped = await chat.map_langgraph_event_to_sse(
        {
            "event": "on_chain_end",
            "name": "tool_executor",
            "data": {
                "output": {
                    "tools_to_call": ["query_service_status"],
                    "tool_results": [
                        {"tool_name": "query_project_manifest", "status": "success", "output": {"summary": "old"}},
                        {"tool_name": "query_service_status", "status": "success", "output": {"status": "healthy"}},
                    ],
                }
            },
        }
    )
    assert mapped is not None
    assert "query_service_status" in mapped
    assert "query_project_manifest" not in mapped


@pytest.mark.asyncio
async def test_answer_generator_chain_end_emits_answer_sse() -> None:
    mapped = await chat.map_langgraph_event_to_sse(
        {
            "event": "on_chain_end",
            "name": "answer_generator",
            "data": {"output": {"answer": "Final answer [1]", "confidence_score": 0.8}},
        }
    )

    assert mapped is not None
    assert mapped.startswith("event: answer\n")
    assert '"content": "Final answer [1]"' in mapped


def test_troubleshooting_route_invokes_tools_once_even_with_sufficient_evidence() -> None:
    from src.agent.graph import route_after_evidence
    from src.agent.state import create_initial_state

    state = create_initial_state("Airflow task failed", trace_id="run-tools")
    state["route"] = "troubleshooting"
    state["evidence_sufficient"] = True
    state["tool_loop_count"] = 0

    assert route_after_evidence(state) == "need_tools"

    state["tool_loop_count"] = 1
    assert route_after_evidence(state) == "sufficient"


@pytest.mark.asyncio
async def test_chat_stream_returns_ordered_sse_chain(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeGraph:
        async def astream_events(self, state: dict, version: str, config: dict) -> AsyncIterator[dict]:
            assert version == "v2"
            yield {
                "event": "on_chain_end",
                "name": "query_router",
                "data": {"output": {**state, "route": "out_of_scope", "workspace_policy": "none"}},
            }

    monkeypatch.setattr(chat, "build_agent_graph", lambda: FakeGraph())
    monkeypatch.setattr(chat, "create_agent_run", AsyncMock(return_value=str(uuid4())))
    monkeypatch.setattr(chat, "complete_agent_run", AsyncMock(return_value=None))
    response = await client.post("/api/v1/chat/stream", json={"query": "test", "workspace_slug": "public_tech"})
    body = response.text
    assert response.status_code == 200
    events = _sse_events(body)
    assert events == ["route", "done"]
    assert '"query_id"' in body


@pytest.mark.asyncio
async def test_real_app_chat_stream_emits_full_sse_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.api.app import app as real_app

    class FakeGraph:
        async def astream_events(self, state: dict, version: str, config: dict) -> AsyncIterator[dict]:
            yield {
                "event": "on_chain_end",
                "name": "query_router",
                "data": {"output": {**state, "route": "tech_general", "workspace_policy": "public_only"}},
            }
            yield {
                "event": "on_chain_end",
                "name": "hybrid_retriever",
                "data": {"output": {**state, "retrieved_chunks": [{"chunk_uid": "doc:section:abc"}]}},
            }
            yield {
                "event": "on_chain_end",
                "name": "reranker",
                "data": {"output": {**state, "reranked_chunks": [{"chunk_uid": "doc:section:abc"}]}},
            }
            yield {
                "event": "on_chain_start",
                "name": "tool_executor",
                "data": {"input": {**state, "tools_to_call": ["query_service_status"], "tool_loop_count": 0}},
            }
            yield {
                "event": "on_chain_end",
                "name": "tool_executor",
                "data": {
                    "output": {
                        **state,
                        "tools_to_call": ["query_service_status"],
                        "tool_results": [
                            {
                                "tool_name": "query_service_status",
                                "status": "success",
                                "output": {"status": "healthy"},
                            }
                        ],
                    }
                },
            }
            yield {"event": "on_chat_model_stream", "name": "answer_generator", "data": {"chunk": {"content": "Answer"}}}
            yield {
                "event": "on_chain_end",
                "name": "citation_verifier",
                "data": {
                    "output": {
                        **state,
                        "answer": "Answer [1]",
                        "citations": [
                            {
                                "index": 1,
                                "chunk_uid": "doc:section:abc",
                                "document_title": "Guide",
                                "score": 0.9,
                                "quote": "Answer",
                            }
                        ],
                    }
                },
            }

    monkeypatch.setattr(chat, "build_agent_graph", lambda: FakeGraph())
    monkeypatch.setattr(chat, "create_agent_run", AsyncMock(return_value=str(uuid4())))
    monkeypatch.setattr(chat, "complete_agent_run", AsyncMock(return_value=None))

    transport = ASGITransport(app=real_app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        response = await http_client.post("/api/v1/chat/stream", json={"query": "test"})

    assert response.status_code == 200
    assert _sse_events(response.text) == [
        "reasoning",
        "route",
        "reasoning",
        "retrieval",
        "reasoning",
        "rerank",
        "reasoning",
        "tool_call",
        "reasoning",
        "tool_result",
        "token",
        "reasoning",
        "citation",
        "done",
    ]


@pytest.mark.asyncio
async def test_chat_stream_emits_heartbeat(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeGraph:
        async def astream_events(self, state: dict, version: str, config: dict) -> AsyncIterator[dict]:
            yield {"event": "heartbeat", "name": "heartbeat", "data": {}}

    monkeypatch.setattr(chat, "build_agent_graph", lambda: FakeGraph())
    monkeypatch.setattr(chat, "create_agent_run", AsyncMock(return_value=str(uuid4())))
    monkeypatch.setattr(chat, "complete_agent_run", AsyncMock(return_value=None))
    response = await client.post("/api/v1/chat/stream", json={"query": "test"})
    assert 'event: token\ndata: {"content": ""}\n\n' in response.text


@pytest.mark.asyncio
async def test_chat_stream_error_type_timeout(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeGraph:
        async def astream_events(self, state: dict, version: str, config: dict) -> AsyncIterator[dict]:
            raise TimeoutError("slow stream")
            yield {}

    monkeypatch.setattr(chat, "build_agent_graph", lambda: FakeGraph())
    monkeypatch.setattr(chat, "create_agent_run", AsyncMock(return_value=str(uuid4())))
    monkeypatch.setattr(chat, "complete_agent_run", AsyncMock(return_value=None))
    response = await client.post("/api/v1/chat/stream", json={"query": "test"})
    assert '"error_type": "timeout"' in response.text


@pytest.mark.asyncio
async def test_api_client_upload_uses_canonical_upload_path(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    async def fake_request_json(method: str, path: str, **kwargs: object) -> dict[str, object]:
        seen["method"] = method
        seen["path"] = path
        return {"ok": True}

    monkeypatch.setattr(api_client, "request_json", fake_request_json)
    await api_client.upload_document("guide.md", b"# Guide", "text/markdown", "public_tech", "tech_doc")
    assert seen == {"method": "POST", "path": "/documents/upload"}


@pytest.mark.asyncio
async def test_api_client_uses_purge_document_path(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, str]] = []

    async def fake_request_json(method: str, path: str, **kwargs: object) -> dict[str, object]:
        seen.append((method, path))
        return {"ok": True}

    monkeypatch.setattr(api_client, "request_json", fake_request_json)

    await api_client.purge_document("doc-1")

    assert seen == [("DELETE", "/documents/doc-1/purge")]


def test_api_client_auth_header_prefers_frontend_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCWISE_ADMIN_TOKEN", "frontend-token")
    monkeypatch.setenv("ADMIN_API_TOKEN", "api-token")
    monkeypatch.setattr(api_client.settings, "admin_api_token", "settings-token")

    assert api_client._headers() == {"Authorization": "Bearer frontend-token"}


def test_api_client_auth_header_falls_back_to_backend_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCWISE_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("ADMIN_API_TOKEN", raising=False)
    monkeypatch.setattr(api_client.settings, "admin_api_token", "settings-token")

    assert api_client._headers() == {"Authorization": "Bearer settings-token"}


@pytest.mark.asyncio
async def test_request_json_converts_read_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    class TimeoutClient:
        async def __aenter__(self) -> TimeoutClient:
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        async def request(self, method: str, path: str, **kwargs: object) -> object:
            raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: TimeoutClient())
    with pytest.raises(TimeoutError):
        await api_client.request_json("GET", "/documents")


@pytest.mark.asyncio
async def test_request_json_converts_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class ErrorClient:
        async def __aenter__(self) -> ErrorClient:
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        async def request(self, method: str, path: str, **kwargs: object) -> httpx.Response:
            request = httpx.Request(method, f"http://test{path}")
            return httpx.Response(503, json={"detail": "backend unavailable"}, request=request)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: ErrorClient())
    with pytest.raises(api_client.ApiClientError, match="503"):
        await api_client.request_json("GET", "/documents")
