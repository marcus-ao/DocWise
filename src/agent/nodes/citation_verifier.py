"""Verify answer citation markers against reranked chunks."""
from __future__ import annotations

import re
import time

from langchain_core.runnables import RunnableConfig

from src.agent._tracer_stub import write_trace_event
from src.agent.state import AgentState

_CITATION_PATTERN = re.compile(r"\[(\d+)\]")


async def citation_verifier(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
    start = time.perf_counter()
    answer = state.get("answer", "")
    chunks = state.get("reranked_chunks", [])
    valid_indices = {str(index) for index in range(1, len(chunks) + 1)}
    requested = _CITATION_PATTERN.findall(answer)
    citations: list[dict] = []

    for raw_index in requested:
        if raw_index not in valid_indices:
            continue
        index = int(raw_index)
        chunk = chunks[index - 1]
        citations.append(
            {
                "index": index,
                "chunk_id": chunk.get("chunk_id"),
                "chunk_uid": chunk.get("chunk_uid", ""),
                "document_id": chunk.get("document_id"),
                "document_title": chunk.get("document_title", ""),
                "section_path": chunk.get("section_path"),
                "page_number": chunk.get("page_number"),
                "score": float(chunk.get("rerank_score") or chunk.get("rrf_score") or 0.0),
                "quote": str(chunk.get("content", "")),
            }
        )

    invalid = [item for item in requested if item not in valid_indices]
    if invalid:
        answer = _remove_invalid_citations(answer, valid_indices)
        state["answer"] = answer
        if not citations and requested:
            state["confidence_score"] = float(state.get("confidence_score") or 0.0) * 0.5

    state["citations"] = citations
    await write_trace_event(
        run_id=state["trace_id"],
        node_name="citation_verifier",
        sequence_no=11,
        status="success",
        input_summary={"answer_length": len(answer)},
        output_summary={"valid_count": len(citations), "invalid_count": len(invalid)},
        latency_ms=int((time.perf_counter() - start) * 1000),
    )
    return state


def _remove_invalid_citations(answer: str, valid_indices: set[str]) -> str:
    return _CITATION_PATTERN.sub(lambda match: match.group(0) if match.group(1) in valid_indices else "", answer)

