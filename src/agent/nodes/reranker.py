"""reranker node — Qwen rerank with RRF-score fallback."""
from __future__ import annotations

import time

import structlog
from langchain_core.runnables import RunnableConfig

from src.agent._tracer_stub import write_retrieval_result, write_trace_event
from src.agent.state import RERANK_TOP_K, AgentState, _append_error
from src.retrieval import reranker

logger = structlog.get_logger(__name__)


async def reranker_node(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
    start = time.perf_counter()
    query = state.get("effective_query") or state["rewritten_query"] or state["original_query"]
    chunks = state["retrieved_chunks"]

    if not chunks:
        state["reranked_chunks"] = []
        elapsed = int((time.perf_counter() - start) * 1000)
        await write_trace_event(
            run_id=state["trace_id"], node_name="reranker", sequence_no=7,
            status="skipped", input_summary={"input_count": 0},
            output_summary={"output_count": 0, "fallback": False}, latency_ms=elapsed,
        )
        return state

    reranked, fallback_used = await reranker.rerank(query, chunks, top_k=RERANK_TOP_K)

    if fallback_used:
        _append_error(state, "reranker API failed, using RRF scores")

    state["reranked_chunks"] = reranked

    for chunk in reranked:
        if not _has_required_retrieval_ids(chunk):
            logger.warning("rerank_result_skipped_missing_ids", chunk_uid=chunk.get("chunk_uid", ""))
            continue
        await write_retrieval_result(
            query_id=state.get("query_id", state["trace_id"]),
            run_id=state["trace_id"],
            chunk_id=chunk.get("chunk_id", ""),
            chunk_uid=chunk.get("chunk_uid", ""),
            document_id=chunk.get("document_id", ""),
            workspace_id=chunk.get("workspace_id", ""),
            vector_score=chunk.get("vector_score"),
            keyword_score=chunk.get("keyword_score"),
            rrf_score=chunk.get("rrf_score"),
            rerank_score=chunk.get("rerank_score"),
            final_rank=chunk.get("final_rank"),
            retrieval_stage="rerank",
        )

    elapsed = int((time.perf_counter() - start) * 1000)
    await write_trace_event(
        run_id=state["trace_id"], node_name="reranker", sequence_no=7,
        status="success",
        input_summary={"input_count": len(chunks), "model": "qwen3-rerank", "effective_query": query[:200]},
        output_summary={
            "output_count": len(reranked),
            "fallback": fallback_used,
            "top_chunk_uids": [c.get("chunk_uid", "") for c in reranked[:3]],
        },
        latency_ms=elapsed,
    )
    return state


def _has_required_retrieval_ids(chunk: dict) -> bool:
    return all(chunk.get(key) for key in ("chunk_id", "chunk_uid", "document_id", "workspace_id"))
