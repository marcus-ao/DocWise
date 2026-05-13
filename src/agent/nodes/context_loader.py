from __future__ import annotations

import time

from langchain_core.runnables import RunnableConfig

from src.agent._tracer_stub import write_trace_event
from src.agent.conversation import load_conversation_context
from src.agent.state import AgentState
from src.db.session import async_session_factory


async def context_loader(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
    start = time.perf_counter()
    state["recent_turns"] = []
    state["context_summary"] = None

    async with async_session_factory() as session:
        payload = await load_conversation_context(
            session,
            query_id=state["query_id"],
            current_run_id=state["trace_id"],
        )

    state["recent_turns"] = payload.recent_turns
    state["context_summary"] = payload.context_summary

    elapsed = int((time.perf_counter() - start) * 1000)
    await write_trace_event(
        run_id=state["trace_id"],
        node_name="context_loader",
        sequence_no=2,
        status="success",
        input_summary={
            "query_id": state["query_id"],
            "turn_index": state.get("turn_index", 0),
        },
        output_summary={
            "loaded_turn_count": payload.loaded_turn_count,
            "recent_turn_indexes": [turn.get("turn_index") for turn in payload.recent_turns],
            "summary_used": payload.summary_used,
            "summary_source": payload.summary_source,
        },
        metadata={
            "loaded_turn_count": payload.loaded_turn_count,
            "recent_turn_indexes": [turn.get("turn_index") for turn in payload.recent_turns],
            "summary_used": payload.summary_used,
            "summary_cache_hit": payload.summary_cache_hit,
            "summary_source": payload.summary_source,
            "summary_latency_ms": payload.summary_latency_ms,
            "excluded_run_ids": payload.excluded_run_ids,
        },
        latency_ms=elapsed,
    )
    return state
