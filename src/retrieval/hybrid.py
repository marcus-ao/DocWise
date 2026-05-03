"""Reciprocal Rank Fusion (RRF) for merging vector and keyword results."""
from __future__ import annotations

from src.agent.state import RETRIEVAL_RRF_K


def rrf_merge(
    vector_results: list[dict],
    keyword_results: list[dict],
    k: int = RETRIEVAL_RRF_K,
) -> list[dict]:
    """Merge two ranked lists using RRF and return de-duplicated results.

    RRF formula: score(d) = sum( 1 / (k + rank_i(d)) )
    """
    scored: dict[str, dict] = {}

    for rank, chunk in enumerate(vector_results, start=1):
        cid = chunk["chunk_id"]
        if cid not in scored:
            scored[cid] = {**chunk, "rrf_score": 0.0}
        scored[cid]["rrf_score"] += 1.0 / (k + rank)
        if chunk.get("vector_score") is not None:
            scored[cid]["vector_score"] = chunk["vector_score"]

    for rank, chunk in enumerate(keyword_results, start=1):
        cid = chunk["chunk_id"]
        if cid not in scored:
            scored[cid] = {**chunk, "rrf_score": 0.0}
        scored[cid]["rrf_score"] += 1.0 / (k + rank)
        if chunk.get("keyword_score") is not None:
            scored[cid]["keyword_score"] = chunk["keyword_score"]

    merged = sorted(scored.values(), key=lambda c: c["rrf_score"], reverse=True)
    return merged
