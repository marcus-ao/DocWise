"""hybrid_retriever — parallel vector + keyword search with RRF merge."""
from __future__ import annotations

import time

import structlog
from langchain_core.runnables import RunnableConfig

from src.agent._tracer_stub import write_retrieval_result, write_trace_event
from src.agent.state import (
    RETRIEVAL_KEYWORD_TOP_K,
    RETRIEVAL_VECTOR_TOP_K,
    AgentState,
    _append_error,
)
from src.db.session import async_session_factory
from src.document.embedder import embed_with_cache
from src.retrieval import hybrid, keyword_search, vector_store
from src.retrieval.metadata_filter import resolve_workspace_ids

logger = structlog.get_logger(__name__)


async def hybrid_retriever(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
    start = time.perf_counter()
    query = state.get("effective_query") or state["rewritten_query"] or state["original_query"]
    ws_ids = state["workspace_ids"]

    if not ws_ids:
        state["retrieved_chunks"] = []
        elapsed = int((time.perf_counter() - start) * 1000)
        await write_trace_event(
            run_id=state["trace_id"], node_name="hybrid_retriever", sequence_no=6,
            status="skipped", input_summary={"query": query[:200], "effective_query": query[:200], "workspace_ids": ws_ids},
            output_summary={"candidate_count": 0}, latency_ms=elapsed,
        )
        return state

    async with async_session_factory() as session:
        uuids = await resolve_workspace_ids(session, ws_ids)

    vector_results: list[dict] = []
    kw_results: list[dict] = []
    embedding_failed = False
    keyword_failed = False

    try:
        query_embedding = await embed_with_cache(query)
        async with async_session_factory() as session:
            vector_results = await vector_store.search(
                session, query_embedding, uuids, top_k=RETRIEVAL_VECTOR_TOP_K,
            )
    except Exception as exc:
        logger.warning("hybrid_retriever_vector_failed", error=str(exc))
        embedding_failed = True
        _append_error(state, "embedding/vector search failed, using keyword only")

    try:
        async with async_session_factory() as session:
            kw_results = await keyword_search.search(session, query, uuids, top_k=RETRIEVAL_KEYWORD_TOP_K)
    except Exception as exc:
        logger.warning("hybrid_retriever_keyword_failed", error=str(exc))
        keyword_failed = True
        _append_error(state, "keyword search failed, using vector only")

    if embedding_failed and keyword_failed:
        state["retrieved_chunks"] = []
        _append_error(state, "both vector and keyword search failed")
    elif embedding_failed:
        for chunk in kw_results:
            chunk["rrf_score"] = chunk.get("keyword_score", 0.0)
        state["retrieved_chunks"] = kw_results
    elif keyword_failed:
        for chunk in vector_results:
            chunk["rrf_score"] = chunk.get("vector_score", 0.0)
        state["retrieved_chunks"] = vector_results
    else:
        merged = hybrid.rrf_merge(vector_results, kw_results)
        state["retrieved_chunks"] = merged

    for chunk in state["retrieved_chunks"]:
        if not _has_required_retrieval_ids(chunk):
            logger.warning("retrieval_result_skipped_missing_ids", chunk_uid=chunk.get("chunk_uid", ""))
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
            retrieval_stage="rrf",
        )

    elapsed = int((time.perf_counter() - start) * 1000)
    await write_trace_event(
        run_id=state["trace_id"], node_name="hybrid_retriever", sequence_no=6,
        status="success",
        input_summary={
            "query": query[:200],
            "effective_query": query[:200],
            "retrieval_query_source": "effective_query",
            "vector_top_k": RETRIEVAL_VECTOR_TOP_K,
            "keyword_top_k": RETRIEVAL_KEYWORD_TOP_K,
        },
        output_summary={"candidate_count": len(state["retrieved_chunks"])},
        latency_ms=elapsed,
    )
    return state


def _has_required_retrieval_ids(chunk: dict) -> bool:
    return all(chunk.get(key) for key in ("chunk_id", "chunk_uid", "document_id", "workspace_id"))
