from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from src.models.agent import AgentRun, ToolCall, TraceEvent
from src.models.query import Query, RetrievalResult
from src.observability import tracer


class FakeSessionContext:
    def __init__(self, session: object) -> None:
        self.session = session

    async def __aenter__(self) -> object:
        return self.session

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class CreateRunSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flush_count = 0
        self.commit_count = 0
        self.flushed_query = False

    async def scalar(self, stmt: object) -> object | None:
        return None

    def add(self, item: object) -> None:
        if isinstance(item, AgentRun) and not self.flushed_query:
            raise AssertionError("AgentRun was added before the parent Query was flushed")
        self.added.append(item)

    async def flush(self) -> None:
        self.flush_count += 1
        self.flushed_query = True

    async def commit(self) -> None:
        self.commit_count += 1


class MissingParentSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commit_count = 0

    async def scalar(self, stmt: object) -> object | None:
        return None

    def add(self, item: object) -> None:
        self.added.append(item)

    async def commit(self) -> None:
        self.commit_count += 1


class ExistingParentSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commit_count = 0

    async def scalar(self, stmt: object) -> object:
        return uuid4()

    def add(self, item: object) -> None:
        self.added.append(item)

    async def commit(self) -> None:
        self.commit_count += 1


@pytest.mark.asyncio
async def test_create_agent_run_flushes_query_before_agent_run(monkeypatch: pytest.MonkeyPatch) -> None:
    session = CreateRunSession()
    query_id = uuid4()
    monkeypatch.setattr(tracer, "async_session_factory", lambda: FakeSessionContext(session))
    monkeypatch.setattr(tracer.settings, "langfuse_enabled", False)

    run_id = await tracer.create_agent_run(query_id=query_id, original_query="Airflow task 失败怎么排查？")

    assert UUID(run_id)
    assert [type(item) for item in session.added] == [Query, AgentRun]
    assert session.added[1].query_id == query_id
    assert session.flush_count == 1
    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_trace_and_tool_writes_skip_when_agent_run_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MissingParentSession()
    monkeypatch.setattr(tracer, "async_session_factory", lambda: FakeSessionContext(session))
    monkeypatch.setattr(tracer.settings, "langfuse_enabled", False)

    await tracer.write_trace_event(
        run_id=uuid4(),
        node_name="input_normalizer",
        sequence_no=1,
        status="success",
        input_summary={},
        output_summary={},
        latency_ms=0,
    )
    await tracer.write_tool_call(
        run_id=uuid4(),
        tool_name="query_service_status",
        call_index=0,
        input_json={},
        output_json={},
    )

    assert session.added == []
    assert session.commit_count == 0


@pytest.mark.asyncio
async def test_observability_writes_when_parents_exist(monkeypatch: pytest.MonkeyPatch) -> None:
    session = ExistingParentSession()
    monkeypatch.setattr(tracer, "async_session_factory", lambda: FakeSessionContext(session))
    monkeypatch.setattr(tracer.settings, "langfuse_enabled", False)

    await tracer.write_trace_event(
        run_id=uuid4(),
        node_name="input_normalizer",
        sequence_no=1,
        status="success",
        input_summary={"original_length": 20},
        output_summary={"cleaned_length": 20},
        latency_ms=0,
    )
    await tracer.write_tool_call(
        run_id=uuid4(),
        tool_name="query_service_status",
        call_index=0,
        input_json={"service_name": "airflow"},
        output_json={"status": "unknown"},
    )
    await tracer.write_retrieval_result(
        query_id=uuid4(),
        run_id=uuid4(),
        chunk_id=uuid4(),
        chunk_uid="doc:chunk:1",
        document_id=uuid4(),
        workspace_id=uuid4(),
    )

    assert [type(item) for item in session.added] == [TraceEvent, ToolCall, RetrievalResult]
    assert session.commit_count == 3
