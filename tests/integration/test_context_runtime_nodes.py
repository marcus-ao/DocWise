from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.agent.context.types import ModelContext
from src.agent.state import create_initial_state


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


@pytest.mark.asyncio
async def test_answer_generator_uses_model_context_messages() -> None:
    from src.agent.nodes.answer_generator import answer_generator

    state = create_initial_state("Airflow task failed", trace_id="run-m1-answer")
    state["route"] = "troubleshooting"
    state["reranked_chunks"] = [_chunk("scheduler oom", index=1)]
    custom_messages = [
        {"role": "system", "content": "custom system"},
        {"role": "user", "content": "custom user"},
    ]
    model_context = ModelContext(
        messages=custom_messages,
        diagnostics={
            "budget": 100,
            "estimated_prompt_tokens": 10,
            "sections": {},
            "truncations": [],
            "compaction_triggered": False,
            "compaction_input_tokens": None,
            "compaction_output_tokens": None,
            "fallback_used": False,
            "fallback_reason": None,
        },
        preview={},
        estimated_prompt_tokens=10,
        compaction_summary=None,
    )

    async def fake_stream(messages, **kwargs):
        assert messages == custom_messages
        yield "custom"
        yield " answer"

    with (
        patch("src.agent.nodes.answer_generator.build_answer_context", new=AsyncMock(return_value=model_context)),
        patch("src.agent.nodes.answer_generator.chat_completion_stream", new=fake_stream),
        patch("src.agent.nodes.answer_generator.write_trace_event", new=AsyncMock()),
    ):
        result = await answer_generator(state)

    assert result["answer"] == "custom answer"


@pytest.mark.asyncio
async def test_tool_planner_context_does_not_send_chunk_content() -> None:
    from src.agent.nodes.tool_planner import tool_planner

    state = create_initial_state("Airflow task 一直失败怎么办？", trace_id="run-m1-planner")
    state["route"] = "troubleshooting"
    state["key_entities"] = ["airflow-scheduler"]
    state["selected_project"] = "project_airflow"
    state["rewritten_query"] = "Airflow task failure troubleshooting"
    state["reranked_chunks"] = [_chunk("VERY_SECRET_CHUNK_BODY_SHOULD_NOT_APPEAR", index=1)]

    async def fake_completion(messages, **kwargs):
        payload = "\n".join(str(message["content"]) for message in messages)
        assert "VERY_SECRET_CHUNK_BODY_SHOULD_NOT_APPEAR" not in payload
        return {
            "content": json.dumps({"tool_params": {"query_service_status": {"service_name": "airflow-scheduler"}}}),
            "usage": {"prompt_tokens": 20, "completion_tokens": 10},
        }

    with (
        patch("src.agent.nodes.tool_planner.chat_completion", new=fake_completion),
        patch("src.agent.nodes.tool_planner.write_trace_event", new=AsyncMock()),
    ):
        result = await tool_planner(state)

    assert "query_service_status" in result["tools_to_call"]


@pytest.mark.asyncio
async def test_tool_planner_does_not_overwrite_effective_query() -> None:
    from src.agent.nodes.tool_planner import tool_planner

    state = create_initial_state("Airflow task 一直失败怎么办？", trace_id="run-m4-planner")
    state["route"] = "troubleshooting"
    state["effective_query"] = "effective rewritten query"

    with (
        patch("src.agent.nodes.tool_planner.chat_completion", new=AsyncMock(return_value={"content": "{\"tool_params\": {}}"})),
        patch("src.agent.nodes.tool_planner.write_trace_event", new=AsyncMock()),
    ):
        await tool_planner(state)

    assert state["effective_query"] == "effective rewritten query"


@pytest.mark.asyncio
async def test_answer_generator_trace_metadata_contains_context_diagnostics() -> None:
    from src.agent.nodes.answer_generator import answer_generator

    state = create_initial_state("FastAPI question", trace_id="run-m1-trace")
    state["route"] = "tech_general"
    state["reranked_chunks"] = [_chunk("middleware content", index=1)]
    preview = {
        "query": {
            "section_kind": "query",
            "item_count": 1,
            "total_chars_before": 10,
            "total_chars_after": 10,
            "token_estimate": 5,
            "items_preview": ["FastAPI question"],
        }
    }
    diagnostics = {
        "budget": 500,
        "estimated_prompt_tokens": 42,
        "sections": preview,
        "truncations": [("retrieval:1", 100)],
        "compaction_triggered": True,
        "compaction_input_tokens": 80,
        "compaction_output_tokens": 20,
        "fallback_used": False,
        "fallback_reason": None,
    }
    model_context = ModelContext(
        messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        diagnostics=diagnostics,
        preview=preview,
        estimated_prompt_tokens=42,
        compaction_summary="- fact",
    )

    async def fake_stream(messages, **kwargs):
        yield "ok"

    with (
        patch("src.agent.nodes.answer_generator.build_answer_context", new=AsyncMock(return_value=model_context)),
        patch("src.agent.nodes.answer_generator.chat_completion_stream", new=fake_stream),
        patch("src.agent.nodes.answer_generator.write_trace_event", new=AsyncMock()) as mock_trace,
    ):
        await answer_generator(state)

    metadata = mock_trace.await_args.kwargs["metadata"]
    assert metadata["context_preview"] == preview
    assert metadata["compaction_triggered"] is True
    assert metadata["compaction_summary_present"] is True


@pytest.mark.asyncio
async def test_answer_generator_legacy_fallback_still_runs() -> None:
    from src.agent.nodes.answer_generator import answer_generator

    state = create_initial_state("Fallback question", trace_id="run-m1-fallback")
    state["route"] = "tech_general"
    state["reranked_chunks"] = [_chunk("fallback chunk", index=1)]

    async def fake_stream(messages, **kwargs):
        yield "legacy"
        yield " path"

    with (
        patch("src.agent.nodes.answer_generator.build_answer_context", new=AsyncMock(side_effect=RuntimeError("boom"))),
        patch("src.agent.nodes.answer_generator.chat_completion_stream", new=fake_stream),
        patch("src.agent.nodes.answer_generator.write_trace_event", new=AsyncMock()) as mock_trace,
    ):
        result = await answer_generator(state)

    metadata = mock_trace.await_args.kwargs["metadata"]
    assert result["answer"] == "legacy path"
    assert metadata["fallback_used"] is True


@pytest.mark.asyncio
async def test_answer_generator_does_not_overwrite_effective_query() -> None:
    from src.agent.nodes.answer_generator import answer_generator

    state = create_initial_state("Airflow task failed", trace_id="run-m4-answer")
    state["route"] = "troubleshooting"
    state["reranked_chunks"] = [_chunk("scheduler oom", index=1)]
    state["effective_query"] = "effective rewritten query"
    model_context = ModelContext(
        messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        diagnostics={
            "budget": 100,
            "estimated_prompt_tokens": 10,
            "sections": {},
            "truncations": [],
            "compaction_triggered": False,
            "compaction_input_tokens": None,
            "compaction_output_tokens": None,
            "fallback_used": False,
            "fallback_reason": None,
        },
        preview={},
        estimated_prompt_tokens=10,
        compaction_summary=None,
    )

    async def fake_stream(messages, **kwargs):
        yield "ok"

    with (
        patch("src.agent.nodes.answer_generator.build_answer_context", new=AsyncMock(return_value=model_context)),
        patch("src.agent.nodes.answer_generator.chat_completion_stream", new=fake_stream),
        patch("src.agent.nodes.answer_generator.write_trace_event", new=AsyncMock()),
    ):
        await answer_generator(state)

    assert state["effective_query"] == "effective rewritten query"
