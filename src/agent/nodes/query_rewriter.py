"""Query rewriting node."""
from __future__ import annotations

import time

import structlog
from langchain_core.runnables import RunnableConfig

from src.agent._tracer_stub import write_trace_event
from src.agent.prompts.rewriter import build_rewriter_messages
from src.agent.state import AgentState
from src.llm.client import chat_completion

logger = structlog.get_logger(__name__)


async def query_rewriter(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
    start = time.perf_counter()
    original = state["original_query"]
    try:
        response = await chat_completion(
            build_rewriter_messages(original),
            model="fast",
            temperature=0,
            timeout=15.0,
        )
        rewritten = str(response.get("content") or "").strip()
    except Exception as exc:  # noqa: BLE001 - rewrite is optional.
        logger.warning("query_rewriter_fallback", error=str(exc))
        rewritten = original

    state["rewritten_query"] = rewritten or original
    await write_trace_event(
        run_id=state["trace_id"],
        node_name="query_rewriter",
        sequence_no=4,
        status="success",
        input_summary={"original_query": original[:200]},
        output_summary={"rewritten_query": state["rewritten_query"][:200]},
        latency_ms=int((time.perf_counter() - start) * 1000),
    )
    return state

