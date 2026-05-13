"""answer_generator — LLM streaming generation with numbered citations."""
from __future__ import annotations

import time

import structlog
from langchain_core.runnables import RunnableConfig

from src.agent._tracer_stub import write_trace_event
from src.agent.context import build_answer_context
from src.agent.prompts.generator import build_generator_messages
from src.agent.state import AgentState, NonRetryableError, RetryableError, _append_error
from src.llm.client import chat_completion_stream

logger = structlog.get_logger(__name__)


async def answer_generator(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
    start = time.perf_counter()
    query = state["original_query"]
    chunks = state["reranked_chunks"]
    tool_results = state.get("tool_results", [])
    route = state["route"]
    error = state.get("error")

    if not chunks and not tool_results:
        state["answer"] = ""
        state["confidence_score"] = 0.0
        elapsed = int((time.perf_counter() - start) * 1000)
        await write_trace_event(
            run_id=state["trace_id"],
            node_name="answer_generator",
            sequence_no=11,
            status="skipped",
            input_summary={"query": query[:200]},
            output_summary={"answer_length": 0},
            latency_ms=elapsed,
        )
        return state

    compaction_summary_present = False
    try:
        model_context = await build_answer_context(
            state,
            recent_turns=state.get("recent_turns") or None,
            context_summary=state.get("context_summary"),
        )
        messages = model_context.messages
        state["working_context_preview"] = model_context.preview
        state["working_context_diagnostics"] = model_context.diagnostics
        compaction_summary_present = bool(model_context.compaction_summary)
    except Exception as exc:  # noqa: BLE001 - explicit legacy fallback for M1 runtime rollout.
        logger.warning("answer_context_runtime_failed", error=str(exc))
        state["working_context_preview"] = {
            "legacy": {
                "section_kind": "query",
                "item_count": 1,
                "total_chars_before": len(query),
                "total_chars_after": len(query),
                "token_estimate": 0,
                "items_preview": [query[:80]],
            }
        }
        state["working_context_diagnostics"] = {
            "budget": 0,
            "estimated_prompt_tokens": 0,
            "sections": state["working_context_preview"],
            "truncations": [],
            "compaction_triggered": False,
            "compaction_input_tokens": None,
            "compaction_output_tokens": None,
            "fallback_used": True,
            "fallback_reason": f"context_builder_error:{exc.__class__.__name__}",
        }
        messages = build_generator_messages(
            query=query, chunks=chunks, tool_results=tool_results,
            route=route, error=error,
        )
    token_sink = None
    if config:
        configurable = config.get("configurable", {})
        token_sink = configurable.get("token_sink")

    try:
        tokens: list[str] = []
        async for token in chat_completion_stream(
            messages, model="fast", temperature=0, timeout=60.0,
        ):
            tokens.append(token)
            if token_sink is not None:
                await token_sink(token)

        answer = "".join(tokens)
        state["answer"] = answer
        state["confidence_score"] = 0.8 if chunks else 0.4

    except RetryableError as exc:
        logger.warning("answer_generator_timeout", error=str(exc))
        state["answer"] = "系统繁忙，请稍后重试。"
        state["refused"] = True
        state["refusal_reason"] = "answer_generator_timeout"
        state["confidence_score"] = 0.0
        _append_error(state, f"answer_generator timeout: {exc}")

    except NonRetryableError as exc:
        logger.warning("answer_generator_error", error=str(exc))
        state["answer"] = "无法生成回答，请稍后重试。"
        state["refused"] = True
        state["refusal_reason"] = "answer_generator_error"
        state["confidence_score"] = 0.0
        _append_error(state, f"answer_generator error: {exc}")

    elapsed = int((time.perf_counter() - start) * 1000)
    await write_trace_event(
        run_id=state["trace_id"], node_name="answer_generator", sequence_no=11,
        status="success" if not state["refused"] else "error",
        input_summary={"query": query[:200], "chunk_count": len(chunks), "model": "fast"},
        output_summary={
            "answer_length": len(state["answer"]),
            "citation_count": state["answer"].count("["),
        },
        metadata={
            "context_preview": state.get("working_context_preview") or {},
            "token_breakdown": (state.get("working_context_diagnostics") or {}).get("sections", {}),
            "truncations": (state.get("working_context_diagnostics") or {}).get("truncations", []),
            "compaction_triggered": bool((state.get("working_context_diagnostics") or {}).get("compaction_triggered", False)),
            "compaction_summary_present": compaction_summary_present,
            "fallback_used": bool((state.get("working_context_diagnostics") or {}).get("fallback_used", False)),
            "fallback_reason": (state.get("working_context_diagnostics") or {}).get("fallback_reason"),
            "estimated_prompt_tokens": (state.get("working_context_diagnostics") or {}).get("estimated_prompt_tokens", 0),
        },
        latency_ms=elapsed,
    )
    return state
