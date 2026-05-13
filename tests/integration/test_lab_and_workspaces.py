"""API tests for /lab/compare and /workspaces endpoints."""
from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.agent.rewriter.result import RewriterResult
from src.api import deps
from src.api.routers import lab, workspaces
from src.models.base import WorkspaceType


class FakeDb:
    async def scalars(self, _stmt: object) -> object:
        class _Rows:
            def all(self) -> list[object]:
                return []

        return _Rows()

    async def scalar(self, _stmt: object) -> object | None:
        return None


async def fake_db() -> AsyncIterator[FakeDb]:
    yield FakeDb()


@pytest.fixture
def app() -> FastAPI:
    test_app = FastAPI()
    test_app.include_router(lab.router, prefix="/api/v1")
    test_app.include_router(workspaces.router, prefix="/api/v1")
    test_app.dependency_overrides[deps.get_db] = fake_db
    return test_app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest.mark.asyncio
async def test_lab_compare_forwards_rrf_and_rerank_top_k(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def fake_resolve(_db: object, slugs: list[str]) -> list[object]:
        return [uuid4() for _ in slugs]

    async def fake_run_strategy(
        _db: object,
        _query: str,
        _workspace_ids: list,
        strategy: str,
        top_k: int,
        _embedding: list[float] | None,
        *,
        rrf_k: int = 60,
        rerank_top_k: int | None = None,
    ) -> list[dict]:
        captured[strategy] = {"top_k": top_k, "rrf_k": rrf_k, "rerank_top_k": rerank_top_k}
        return []

    async def fake_embed(_query: str) -> list[float]:
        return [0.0] * 4

    monkeypatch.setattr(lab, "resolve_workspace_ids", fake_resolve)
    monkeypatch.setattr(lab, "_run_strategy", fake_run_strategy)
    monkeypatch.setattr(lab, "embed_with_cache", fake_embed)
    monkeypatch.setattr(
        lab,
        "rewrite_query",
        AsyncMock(
            return_value=RewriterResult(
                original_query="Airflow scheduler",
                rewritten_query="Airflow scheduler",
                effective_query="Airflow scheduler",
                route="tech_general",
                history_used=False,
                fallback_reason="",
                missing_entities=[],
                diagnostic_hint=None,
            )
        ),
    )

    response = await client.post(
        "/api/v1/lab/compare",
        json={
            "query": "Airflow scheduler",
            "workspace_ids": ["public_tech"],
            "strategies": ["vector_only", "hybrid", "hybrid_rerank"],
            "top_k": 7,
            "rrf_k": 100,
            "rerank_top_k": 3,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body["results"].keys()) == {"vector_only", "hybrid", "hybrid_rerank"}
    assert captured["hybrid"]["rrf_k"] == 100
    assert captured["hybrid_rerank"]["rerank_top_k"] == 3
    assert captured["vector_only"]["top_k"] == 7
    assert body["rewriter"]["effective_query"] == "Airflow scheduler"


@pytest.mark.asyncio
async def test_lab_compare_supports_rewriter_toggle_and_route_override(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    async def fake_resolve(_db: object, slugs: list[str]) -> list[object]:
        return [uuid4() for _ in slugs]

    async def fake_run_strategy(
        _db: object,
        query: str,
        _workspace_ids: list,
        strategy: str,
        top_k: int,
        _embedding: list[float] | None,
        **_: object,
    ) -> list[dict]:
        captured["query"] = query
        captured["strategy"] = strategy
        captured["top_k"] = top_k
        return []

    monkeypatch.setattr(lab, "resolve_workspace_ids", fake_resolve)
    monkeypatch.setattr(lab, "_run_strategy", fake_run_strategy)
    monkeypatch.setattr(lab, "embed_with_cache", AsyncMock(return_value=[0.0] * 4))
    monkeypatch.setattr(
        lab,
        "rewrite_query",
        AsyncMock(
            return_value=RewriterResult(
                original_query="那 task 超时呢？",
                rewritten_query="Airflow task timeout troubleshooting",
                effective_query="Airflow task timeout troubleshooting",
                route="troubleshooting",
                history_used=True,
                fallback_reason="",
                missing_entities=[],
                diagnostic_hint=None,
            )
        ),
    )

    response = await client.post(
        "/api/v1/lab/compare",
        json={
            "query": "那 task 超时呢？",
            "workspace_ids": ["public_tech"],
            "strategies": ["vector_only"],
            "use_rewriter": True,
            "route_override": "troubleshooting",
            "recent_turns": [{"query": "Airflow 报错怎么办？", "answer": "先看日志", "tool_facts": []}],
            "context_summary": "当前在排查 Airflow scheduler 故障。",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["rewriter"]["route"] == "troubleshooting"
    assert body["rewriter"]["effective_query"] == "Airflow task timeout troubleshooting"
    assert captured["query"] == "Airflow task timeout troubleshooting"


@pytest.mark.asyncio
async def test_lab_compare_can_disable_rewriter(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_resolve(_db: object, slugs: list[str]) -> list[object]:
        return [uuid4() for _ in slugs]

    async def fake_run_strategy(
        _db: object,
        query: str,
        _workspace_ids: list,
        _strategy: str,
        _top_k: int,
        _embedding: list[float] | None,
        **_: object,
    ) -> list[dict]:
        assert query == "raw query"
        return []

    monkeypatch.setattr(lab, "resolve_workspace_ids", fake_resolve)
    monkeypatch.setattr(lab, "_run_strategy", fake_run_strategy)
    monkeypatch.setattr(lab, "embed_with_cache", AsyncMock(return_value=[0.0] * 4))

    response = await client.post(
        "/api/v1/lab/compare",
        json={
            "query": "raw query",
            "workspace_ids": ["public_tech"],
            "strategies": ["vector_only"],
            "use_rewriter": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["rewriter"]["used"] is False
    assert body["rewriter"]["effective_query"] == "raw query"


@pytest.mark.asyncio
async def test_lab_compare_rejects_empty_query(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/lab/compare",
        json={"query": "   ", "strategies": ["vector_only"]},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_lab_compare_rejects_unknown_strategy_only(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/lab/compare",
        json={"query": "hi", "strategies": ["unknown_strategy"]},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_list_workspaces_returns_active_items(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = SimpleNamespace(
        id=uuid4(),
        slug="public_tech",
        name="Public Tech",
        workspace_type=WorkspaceType.public_tech,
        project_name=None,
        description="公共技术文档",
        is_active=True,
    )

    class RowsDb:
        async def scalars(self, _stmt: object) -> object:
            class _Rows:
                def all(self) -> list[object]:
                    return [workspace]

            return _Rows()

    async def override_db() -> AsyncIterator[RowsDb]:
        yield RowsDb()

    client._transport.app.dependency_overrides[deps.get_db] = override_db  # type: ignore[attr-defined]

    response = await client.get("/api/v1/workspaces")
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["slug"] == "public_tech"
    assert item["workspace_type"] == "public_tech"
    assert item["is_active"] is True
