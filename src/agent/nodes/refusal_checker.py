"""Final refusal policy checks."""
from __future__ import annotations

import time

from langchain_core.runnables import RunnableConfig

from src.agent._tracer_stub import write_trace_event
from src.agent.prompts.refusal import get_refusal_answer
from src.agent.state import REFUSAL_CONFIDENCE_THRESHOLD, AgentState


async def refusal_checker(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
    start = time.perf_counter()
    route = state.get("route")
    if route == "out_of_scope":
        state["refused"] = True
        state["refusal_reason"] = "out_of_scope"
        state["answer"] = get_refusal_answer("out_of_scope")
        state["citations"] = []
    elif not state.get("answer") and not state.get("evidence_sufficient"):
        state["refused"] = True
        state["refusal_reason"] = "no_evidence"
        state["answer"] = get_refusal_answer("no_evidence")
        state["citations"] = []
    elif state.get("confidence_score", 0.0) < REFUSAL_CONFIDENCE_THRESHOLD and not state.get("citations"):
        state["refused"] = True
        state["refusal_reason"] = "low_confidence"

    await write_trace_event(
        run_id=state["trace_id"],
        node_name="refusal_checker",
        sequence_no=12,
        status="success",
        input_summary={
            "route": route,
            "route_confidence": state.get("route_confidence"),
            "evidence_sufficient": state.get("evidence_sufficient"),
            "reranked_count": len(state.get("reranked_chunks", [])),
        },
        output_summary={"refused": state.get("refused"), "refusal_reason": state.get("refusal_reason")},
        latency_ms=int((time.perf_counter() - start) * 1000),
    )
    return state

