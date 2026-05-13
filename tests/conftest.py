"""Shared test fixtures for DocWise test suite."""
from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import AsyncGenerator, Callable, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config.settings import settings

MOCK_DIR = Path(__file__).resolve().parent.parent / "data" / "mock"
EVAL_DIR = Path(__file__).resolve().parent.parent / "data" / "eval"


@pytest.fixture
def tmp_path() -> Iterator[Path]:
    """Provide a repo-local temp directory to avoid Windows global temp permission issues."""
    root = Path(__file__).resolve().parent.parent / ".tmp" / "pytest"
    root.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(prefix="case-", dir=root))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a test async DB session with automatic rollback."""
    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        async with session.begin():
            yield session
            await session.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def http_client() -> AsyncGenerator[AsyncClient, None]:
    """Provide a test HTTP client against the FastAPI app."""
    from src.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def mock_data_loader() -> Callable[[str], dict | list]:
    """Load a mock data file by name from data/mock/."""
    def _load(filename: str) -> dict | list:
        path = MOCK_DIR / filename
        return json.loads(path.read_text(encoding="utf-8"))
    return _load


@pytest.fixture
def eval_data_loader() -> Callable[[str], list[dict]]:
    """Load eval JSONL file by name from data/eval/."""
    def _load(filename: str) -> list[dict]:
        path = EVAL_DIR / filename
        return [json.loads(line) for line in path.read_text(encoding="utf-8").strip().splitlines()]
    return _load


@pytest.fixture
def sample_eval_case() -> dict:
    """A representative eval case for unit tests."""
    return {
        "case_id": "qa_test_001",
        "query": "Airflow task 一直失败怎么排查？",
        "route": "troubleshooting",
        "workspace_slug": "project_airflow",
        "expected_workspace_ids": ["project_airflow", "public_tech"],
        "expected_answer_points": ["检查日志", "确认数据库连接"],
        "expected_tools": ["query_project_manifest", "query_service_status", "query_mock_logs"],
        "expected_chunk_uids": ["airflow-runbook:task-failure:*"],
        "expected_citations": ["airflow-runbook:task-failure:*"],
        "should_refuse": False,
        "tags": ["airflow", "tools"],
    }


@pytest.fixture
def sample_agent_state() -> dict:
    """A representative AgentState output for unit tests."""
    return {
        "original_query": "Airflow task 一直失败怎么排查？",
        "rewritten_query": "Airflow task failure troubleshooting",
        "route": "troubleshooting",
        "route_confidence": 0.92,
        "workspace_policy": "selected_project_plus_public",
        "workspace_ids": ["project_airflow", "public_tech"],
        "selected_project": "project_airflow",
        "selected_workspace_slug": "project_airflow",
        "display_workspace_slug": "project_airflow",
        "effective_workspace_slugs": ["project_airflow", "public_tech"],
        "scope_reason_code": "auto_project_matched",
        "scope_reason_params": {"project_slug": "project_airflow"},
        "workspace_alias_hits": ["project_airflow"],
        "key_entities": ["airflow", "task"],
        "retrieved_chunks": [],
        "reranked_chunks": [
            {
                "chunk_uid": "airflow-runbook:task-failure:a3f2c1",
                "content": "...", "rerank_score": 0.85, "final_rank": 1,
            },
            {
                "chunk_uid": "airflow-docs:logging:b4e3d2",
                "content": "...", "rerank_score": 0.72, "final_rank": 2,
            },
        ],
        "evidence_sufficient": True,
        "tools_to_call": [],
        "tool_results": [
            {"tool_name": "query_project_manifest", "status": "success", "output": {}, "error": None},
            {"tool_name": "query_service_status", "status": "success", "output": {}, "error": None},
            {"tool_name": "query_mock_logs", "status": "success", "output": {}, "error": None},
        ],
        "tool_loop_count": 1,
        "answer": "排查 Airflow task 失败需要检查 scheduler 和 worker 日志...",
        "citations": [
            {
                "index": 1,
                "chunk_uid": "airflow-runbook:task-failure:a3f2c1",
                "document_title": "Airflow Runbook",
                "section_path": "Task Failure",
                "score": 0.85,
                "quote": "...",
            },
        ],
        "confidence_score": 0.88,
        "refused": False,
        "refusal_reason": None,
        "trace_id": "00000000-0000-0000-0000-000000000001",
        "error": None,
    }
