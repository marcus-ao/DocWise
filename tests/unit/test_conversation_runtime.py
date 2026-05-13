from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from src.agent import conversation
from src.db import session as db_session_module
from src.agent.nodes.query_router import query_router
from src.agent.rewriter import RewriterResult
from src.agent.state import create_initial_state
from src.models.agent import AgentRun, ToolCall
from src.models.base import AgentRunStatus, ToolCallStatus
from src.models.query import Query

query_rewriter_module = importlib.import_module("src.agent.nodes.query_rewriter")


class ConversationSession:
    def __init__(self, *, query: Query | None = None, latest_run: AgentRun | None = None) -> None:
        self.query = query
        self.latest_run = latest_run
        self.added: list[object] = []
        self.statements: list[str] = []
        self.flush_count = 0
        self.commit_count = 0
        self.rollback_count = 0

    async def scalar(self, stmt: object) -> object | None:
        self.statements.append(str(stmt))
        text = str(stmt)
        if "FROM queries" in text:
            return self.query
        if "FROM agent_runs" in text:
            return self.latest_run
        return None

    def add(self, item: object) -> None:
        self.added.append(item)
        if isinstance(item, Query):
            self.query = item

    async def flush(self) -> None:
        self.flush_count += 1

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class LoadContextSession:
    def __init__(self, query: Query, runs: list[AgentRun], tool_calls: list[ToolCall]) -> None:
        self.query = query
        self.runs = runs
        self.tool_calls = tool_calls
        self.commit_count = 0

    async def get(self, model: object, key: object) -> Query | None:
        return self.query

    async def scalars(self, stmt: object) -> SimpleNamespace:
        text = str(stmt)
        if "FROM agent_runs" in text:
            return SimpleNamespace(all=lambda: list(self.runs))
        if "FROM tool_calls" in text:
            return SimpleNamespace(all=lambda: list(self.tool_calls))
        return SimpleNamespace(all=lambda: [])

    async def commit(self) -> None:
        self.commit_count += 1


class RefreshSummarySession:
    def __init__(self, query: Query, runs: list[AgentRun], tool_calls: list[ToolCall]) -> None:
        self.query = query
        self.runs = runs
        self.tool_calls = tool_calls
        self.commit_count = 0

    async def get(self, model: object, key: object) -> Query | None:
        return self.query

    async def scalars(self, stmt: object) -> SimpleNamespace:
        text = str(stmt)
        if "FROM agent_runs" in text:
            return SimpleNamespace(all=lambda: list(self.runs))
        if "FROM tool_calls" in text:
            return SimpleNamespace(all=lambda: list(self.tool_calls))
        return SimpleNamespace(all=lambda: [])

    async def commit(self) -> None:
        self.commit_count += 1


class _RefreshSessionContext:
    def __init__(self, session: RefreshSummarySession) -> None:
        self.session = session

    async def __aenter__(self) -> RefreshSummarySession:
        return self.session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


@pytest.mark.asyncio
async def test_prepare_stream_conversation_run_uses_query_lock_and_turn_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    qid = uuid4()
    latest = AgentRun(
        id=uuid4(),
        query_id=qid,
        turn_index=2,
        original_query="上一轮",
        status=AgentRunStatus.succeeded,
    )
    session = ConversationSession(
        query=Query(id=qid, original_query="seed"),
        latest_run=latest,
    )

    monkeypatch.setattr(conversation, "create_agent_run", AsyncMock(return_value="run-123"))

    prepared = await conversation.prepare_stream_conversation_run(
        session,
        conversation_id=qid,
        original_query="这一轮",
        workspace_slug="public_tech",
    )

    assert prepared.conversation_id == qid
    assert prepared.turn_index == 3
    assert prepared.parent_run_id == latest.id
    assert any("FOR UPDATE" in stmt for stmt in session.statements)
    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_prepare_stream_conversation_run_retries_once_on_integrity_error(monkeypatch: pytest.MonkeyPatch) -> None:
    session = SimpleNamespace(rollback=AsyncMock())
    qid = uuid4()
    success = conversation.PreparedConversationRun(
        conversation_id=qid,
        run_id="run-ok",
        turn_index=1,
        parent_run_id=None,
    )
    integrity_error = IntegrityError("insert", {}, RuntimeError("duplicate"))
    attempts = AsyncMock(side_effect=[integrity_error, success])
    monkeypatch.setattr(conversation, "_prepare_stream_conversation_run_once", attempts)

    prepared = await conversation.prepare_stream_conversation_run(
        session,
        conversation_id=qid,
        original_query="test",
        workspace_slug="public_tech",
    )

    assert prepared.run_id == "run-ok"
    assert attempts.await_count == 2
    assert session.rollback.await_count == 1


@pytest.mark.asyncio
async def test_load_conversation_context_excludes_cancelled_and_failed_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    qid = uuid4()
    current_run_id = uuid4()
    query = Query(id=qid, original_query="seed")
    runs = [
        AgentRun(
            id=current_run_id,
            query_id=qid,
            turn_index=4,
            original_query="current",
            answer="",
            status=AgentRunStatus.running,
        ),
        AgentRun(
            id=uuid4(),
            query_id=qid,
            turn_index=0,
            original_query="turn0",
            answer="ans0",
            status=AgentRunStatus.succeeded,
        ),
        AgentRun(
            id=uuid4(),
            query_id=qid,
            turn_index=1,
            original_query="turn1",
            answer="ans1",
            status=AgentRunStatus.succeeded,
        ),
        AgentRun(
            id=uuid4(),
            query_id=qid,
            turn_index=2,
            original_query="turn2",
            answer="ans2",
            status=AgentRunStatus.succeeded,
        ),
        AgentRun(
            id=uuid4(),
            query_id=qid,
            turn_index=3,
            original_query="turn3",
            answer="ans3",
            status=AgentRunStatus.succeeded,
        ),
        AgentRun(
            id=uuid4(),
            query_id=qid,
            turn_index=4,
            original_query="cancelled",
            answer="partial",
            status=AgentRunStatus.succeeded,
            error_message=conversation.CANCELLED_RUN_MARKER,
        ),
        AgentRun(
            id=uuid4(),
            query_id=qid,
            turn_index=6,
            original_query="failed",
            answer="",
            status=AgentRunStatus.failed,
        ),
    ]
    tool_calls = [
        ToolCall(
            id=uuid4(),
            run_id=runs[1].id,
            tool_name="query_service_status",
            call_index=0,
            input_json={},
            output_json={"service_name": "airflow", "status": "degraded", "active_alerts": ["a1"]},
            status=ToolCallStatus.success,
        ),
        ToolCall(
            id=uuid4(),
            run_id=runs[2].id,
            tool_name="search_docs",
            call_index=0,
            input_json={},
            output_json={"summary": "ignored"},
            status=ToolCallStatus.success,
        ),
    ]
    session = LoadContextSession(query=query, runs=runs, tool_calls=tool_calls)
    monkeypatch.setattr(conversation, "_generate_context_summary", AsyncMock(return_value="summary"))

    payload = await conversation.load_conversation_context(
        session,
        query_id=qid,
        current_run_id=current_run_id,
    )

    assert [turn["turn_index"] for turn in payload.recent_turns] == [1, 2, 3]
    assert payload.context_summary == "summary"
    assert payload.summary_source == "generated"
    assert payload.summary_cache_hit is False
    assert payload.excluded_run_ids["current"] == [str(current_run_id)]
    assert payload.excluded_run_ids["cancelled"] == [str(runs[5].id)]
    assert payload.excluded_run_ids["failed_empty"] == [str(runs[6].id)]
    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_refresh_context_summary_preserves_existing_summary_when_regeneration_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    qid = uuid4()
    query = Query(id=qid, original_query="seed", context_summary="existing summary")
    runs = [
        AgentRun(
            id=uuid4(),
            query_id=qid,
            turn_index=0,
            original_query="turn0",
            answer="ans0",
            status=AgentRunStatus.succeeded,
        ),
        AgentRun(
            id=uuid4(),
            query_id=qid,
            turn_index=1,
            original_query="turn1",
            answer="ans1",
            status=AgentRunStatus.succeeded,
        ),
        AgentRun(
            id=uuid4(),
            query_id=qid,
            turn_index=2,
            original_query="turn2",
            answer="ans2",
            status=AgentRunStatus.succeeded,
        ),
        AgentRun(
            id=uuid4(),
            query_id=qid,
            turn_index=3,
            original_query="turn3",
            answer="ans3",
            status=AgentRunStatus.succeeded,
        ),
    ]
    session = RefreshSummarySession(query=query, runs=runs, tool_calls=[])
    monkeypatch.setattr(db_session_module, "async_session_factory", lambda: _RefreshSessionContext(session))
    monkeypatch.setattr(conversation, "_generate_context_summary", AsyncMock(return_value=None))

    await conversation.refresh_context_summary(qid)

    assert query.context_summary == "existing summary"
    assert session.commit_count == 0


@pytest.mark.asyncio
async def test_query_router_out_of_scope_not_polluted_by_history() -> None:
    state = create_initial_state("帮我预测明天股票走势", trace_id="router-oos")
    state["recent_turns"] = [
        {"turn_index": 0, "query": "Airflow task 超时", "answer": "检查 scheduler", "tool_facts": []}
    ]
    state["context_summary"] = "之前在讨论 Airflow 故障排查。"

    result = await query_router(state)

    assert result["route"] == "out_of_scope"


@pytest.mark.asyncio
async def test_query_rewriter_uses_route_and_history(monkeypatch: pytest.MonkeyPatch) -> None:
    state = create_initial_state("那 task 超时呢？", trace_id="rewriter-history")
    state["route"] = "troubleshooting"
    state["recent_turns"] = [
        {"turn_index": 1, "query": "Airflow scheduler 报错怎么办？", "answer": "先看日志", "tool_facts": []}
    ]
    state["context_summary"] = "当前在排查 Airflow scheduler 故障。"

    captured: dict[str, object] = {}

    async def fake_rewrite_query(**kwargs: object) -> RewriterResult:
        captured.update(kwargs)
        return RewriterResult(
            original_query=str(kwargs["original_query"]),
            rewritten_query="Airflow task timeout troubleshooting",
            effective_query="Airflow task timeout troubleshooting",
            route=str(kwargs["route"]),
            history_used=True,
            fallback_reason="",
        )

    monkeypatch.setattr(query_rewriter_module, "rewrite_query", fake_rewrite_query)
    monkeypatch.setattr(query_rewriter_module, "write_trace_event", AsyncMock())

    result = await query_rewriter_module.query_rewriter(state)

    assert captured["route"] == "troubleshooting"
    assert captured["recent_turns"]
    assert captured["context_summary"] == state["context_summary"]
    assert result["rewritten_query"] == "Airflow task timeout troubleshooting"
