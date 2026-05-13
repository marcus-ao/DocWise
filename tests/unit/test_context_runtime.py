from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.agent.context import build_answer_context, build_tool_planner_context
from src.agent.state import create_initial_state


def _dense_text(prefix: str, words: int) -> str:
    return " ".join(f"{prefix}_{index:04d}" for index in range(words))


def _chunk(content: str, *, score: float = 0.9, index: int = 1) -> dict:
    return {
        "chunk_id": f"chunk-{index}",
        "chunk_uid": f"doc:section:{index}",
        "content": content,
        "document_title": f"Doc {index}",
        "section_path": f"Section {index}",
        "rerank_score": score,
        "final_rank": index,
    }


def _tool_result(text: str, *, status: str = "success", index: int = 1, error: str | None = None) -> dict:
    payload = {"summary": text} if error is None else None
    return {
        "tool_name": f"tool-{index}",
        "status": status,
        "output": payload,
        "error": error,
    }


def _answer_state() -> dict:
    state = create_initial_state("Airflow scheduler fail 怎么办？", trace_id="ctx-1")
    state["route"] = "troubleshooting"
    state["rewritten_query"] = "Airflow scheduler fail troubleshooting"
    state["reranked_chunks"] = [
        _chunk("A" * 900, score=0.92, index=1),
        _chunk("B" * 850, score=0.61, index=2),
        _chunk("C" * 820, score=0.18, index=3),
    ]
    state["tool_results"] = [
        _tool_result("manifest owner=platform team; service=airflow-scheduler", index=1),
        _tool_result("service degraded with OOMKilled and high restart count", index=2),
        _tool_result("error logs mention executor timeout and task heartbeat lag", index=3),
    ]
    return state


@pytest.mark.asyncio
async def test_builder_empty_state() -> None:
    state = create_initial_state("What is FastAPI middleware?", trace_id="ctx-empty")
    context = await build_answer_context(state, budget_override=4000)

    assert len(context.messages) == 2
    assert context.diagnostics["sections"]["retrieval"]["item_count"] == 0
    assert context.diagnostics["sections"]["tool_result"]["item_count"] == 0
    assert context.compaction_summary is None


@pytest.mark.asyncio
async def test_builder_exact_budget() -> None:
    state = _answer_state()
    baseline = await build_answer_context(state, budget_override=12000)
    limit = baseline.estimated_prompt_tokens

    with patch("src.agent.context.builder.safe_budget", return_value=limit):
        context = await build_answer_context(state, budget_override=12000)

    assert context.estimated_prompt_tokens <= limit
    assert context.diagnostics["fallback_used"] is False


@pytest.mark.asyncio
async def test_builder_one_token_over() -> None:
    state = _answer_state()
    baseline = await build_answer_context(state, budget_override=12000)
    limit = max(1, baseline.estimated_prompt_tokens - 1)

    with patch("src.agent.context.builder.safe_budget", return_value=limit):
        context = await build_answer_context(state, budget_override=12000)

    assert context.estimated_prompt_tokens <= limit
    assert context.diagnostics["compaction_triggered"] or context.diagnostics["truncations"]


@pytest.mark.asyncio
async def test_builder_3x_budget() -> None:
    state = _answer_state()
    state["reranked_chunks"] = [_chunk(_dense_text(f"retrieval{i}", 700), score=0.95, index=i) for i in range(1, 7)]
    state["tool_results"] = [_tool_result(_dense_text(f"tool{i}", 520), index=i) for i in range(1, 4)]

    with (
        patch("src.agent.context.builder.safe_budget", return_value=500),
        patch(
            "src.agent.context.builder.summarize_overflow",
            new=AsyncMock(return_value=("- [retrieval] compressed fact\n- [tool_result] compressed fact", 120, 40)),
        ),
    ):
        context = await build_answer_context(state, budget_override=1600)

    assert context.diagnostics["compaction_triggered"] is True
    assert context.compaction_summary is not None
    assert "compressed fact" in context.compaction_summary


@pytest.mark.asyncio
async def test_builder_system_prompt_too_large() -> None:
    state = create_initial_state("tiny", trace_id="ctx-system")

    with patch("src.agent.context.builder.safe_budget", return_value=1):
        context = await build_answer_context(state, budget_override=1)

    assert context.messages[1]["content"] == ""
    assert context.diagnostics["fallback_used"] is False


@pytest.mark.asyncio
async def test_builder_tool_planner_no_chunk_content() -> None:
    state = _answer_state()
    state["tools_to_call"] = ["query_project_manifest", "query_service_status"]
    state["key_entities"] = ["airflow-scheduler"]
    state["selected_project"] = "project_airflow"
    secret = "VERY_SECRET_CHUNK_BODY_SHOULD_NOT_APPEAR"
    state["reranked_chunks"][0]["content"] = secret

    context = await build_tool_planner_context(state, budget_override=4000)
    joined = "\n".join(str(message["content"]) for message in context.messages)

    assert secret not in joined
    assert "Doc 1 > Section 1" in joined


@pytest.mark.asyncio
async def test_compaction_llm_failure_degrades_to_hard_truncate() -> None:
    state = _answer_state()
    state["reranked_chunks"] = [_chunk(_dense_text(f"retrieval{i}", 620), score=0.95, index=i) for i in range(1, 6)]
    state["tool_results"] = [_tool_result(_dense_text(f"tool{i}", 480), index=i) for i in range(1, 4)]

    with (
        patch("src.agent.context.builder.safe_budget", return_value=500),
        patch("src.agent.context.builder.summarize_overflow", new=AsyncMock(side_effect=RuntimeError("boom"))),
    ):
        context = await build_answer_context(state, budget_override=1500)

    assert context.diagnostics["compaction_triggered"] is True
    assert context.compaction_summary is None
    assert context.diagnostics["fallback_used"] is False


@pytest.mark.asyncio
async def test_builder_exception_falls_back_to_legacy() -> None:
    from src.agent.nodes.answer_generator import answer_generator

    state = _answer_state()
    state["trace_id"] = "ctx-fallback"

    async def fake_stream(messages, **kwargs):
        yield "fallback answer"

    with (
        patch("src.agent.nodes.answer_generator.build_answer_context", new=AsyncMock(side_effect=RuntimeError("builder down"))),
        patch("src.agent.nodes.answer_generator.chat_completion_stream", new=fake_stream),
        patch("src.agent.nodes.answer_generator.write_trace_event", new=AsyncMock()) as mock_trace,
    ):
        result = await answer_generator(state)

    metadata = mock_trace.await_args.kwargs["metadata"]
    assert result["answer"] == "fallback answer"
    assert metadata["fallback_used"] is True
    assert metadata["fallback_reason"] == "context_builder_error:RuntimeError"
