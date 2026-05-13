"""Query rewriting node."""
from __future__ import annotations

import time

import structlog
from langchain_core.runnables import RunnableConfig

from src.agent._tracer_stub import write_trace_event
from src.agent.rewriter import rewrite_query
from src.agent.state import AgentState
from src.config.settings import settings

logger = structlog.get_logger(__name__)


async def query_rewriter(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
    start = time.perf_counter()
    original = state["original_query"]
    route = state["route"]
    result = await rewrite_query(
        original_query=original,
        route=route,
        key_entities=[str(item) for item in state.get("key_entities") or []]
        + ([str(state.get("selected_project"))] if state.get("selected_project") else []),
        recent_turns=state.get("recent_turns") or None,
        context_summary=state.get("context_summary"),
    )
    state["rewritten_query"] = result.rewritten_query or result.original_query
    state["effective_query"] = result.effective_query or result.original_query
    await write_trace_event(
        run_id=state["trace_id"],
        node_name="query_rewriter",
        sequence_no=5,
        status="success",
        input_summary={"original_query": original[:200], "route": route},
        output_summary={
            "rewritten_query": state["rewritten_query"][:200],
            "effective_query": state["effective_query"][:200],
        },
        metadata={
            "history_used": result.history_used,
            "recent_turn_count": len(state.get("recent_turns") or []),
            "context_summary_present": bool(state.get("context_summary")),
            "rewriter_use_history": bool(settings.rewriter_use_history),
            "fallback_reason": result.fallback_reason or None,
            "missing_entities": result.missing_entities,
            "diagnostic_hint": result.diagnostic_hint,
        },
        latency_ms=int((time.perf_counter() - start) * 1000),
    )
    return state

