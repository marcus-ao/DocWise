"""Evidence sufficiency checks."""
from __future__ import annotations

import time

from langchain_core.runnables import RunnableConfig

from src.agent._tracer_stub import write_trace_event
from src.agent.state import EVIDENCE_MIN_CHUNKS, EVIDENCE_MIN_RERANK_SCORE, EVIDENCE_MIN_RRF_SCORE, AgentState


async def evidence_validator(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
    start = time.perf_counter()
    chunks = state.get("reranked_chunks", [])
    sufficient_chunks = [
        chunk
        for chunk in chunks
        if float(chunk.get("rerank_score") or chunk.get("rrf_score") or 0.0)
        >= (EVIDENCE_MIN_RERANK_SCORE if chunk.get("rerank_score") is not None else EVIDENCE_MIN_RRF_SCORE)
    ]
    state["evidence_sufficient"] = len(sufficient_chunks) >= EVIDENCE_MIN_CHUNKS
    reason = "sufficient" if state["evidence_sufficient"] else "no reranked chunks" if not chunks else "low score"
    await write_trace_event(
        run_id=state["trace_id"],
        node_name="evidence_validator",
        sequence_no=8,
        status="success",
        input_summary={"chunk_count": len(chunks)},
        output_summary={"evidence_sufficient": state["evidence_sufficient"], "reason": reason},
        latency_ms=int((time.perf_counter() - start) * 1000),
    )
    return state

