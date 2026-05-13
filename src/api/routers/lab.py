"""Retrieval comparison API for the Next.js lab page."""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, status

from src.agent.nodes.query_router import _rule_route
from src.agent.rewriter import RewriterResult, rewrite_query
from src.api.deps import DbSession
from src.config.redactor import redact_secrets
from src.document.embedder import embed_with_cache
from src.retrieval import hybrid, keyword_search, reranker, vector_store
from src.retrieval.metadata_filter import resolve_workspace_ids
from src.schemas.frontend import (
    LabChunkResult,
    LabCompareRequest,
    LabCompareResponse,
    LabRewriterInfo,
)

router = APIRouter(prefix="/lab", tags=["lab"])

VALID_STRATEGIES = {"vector_only", "keyword_only", "hybrid", "hybrid_rerank"}
VALID_LAB_ROUTES = {
    "tech_general",
    "project_specific",
    "troubleshooting",
    "runbook_generation",
}


@router.post("/compare", response_model=LabCompareResponse)
async def compare_retrieval_strategies(db: DbSession, request: LabCompareRequest) -> LabCompareResponse:
    strategies = [strategy for strategy in request.strategies if strategy in VALID_STRATEGIES]
    if not request.query.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="query must not be empty")
    if not strategies:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="no supported strategies requested")

    route = _resolve_lab_route(request)
    rewriter_result = await _resolve_lab_rewriter(request, route)
    retrieval_query = rewriter_result.effective_query
    workspace_ids = await resolve_workspace_ids(db, request.workspace_ids)
    if not workspace_ids:
        return LabCompareResponse(
            results={strategy: [] for strategy in strategies},
            overlap_matrix={},
            timing_ms={},
            rewriter=_lab_rewriter_info(rewriter_result, used=request.use_rewriter),
        )

    embedding: list[float] | None = None
    results: dict[str, list[LabChunkResult]] = {}
    timing_ms: dict[str, int] = {}
    errors: dict[str, str] = {}

    for strategy in strategies:
        started = time.perf_counter()
        try:
            if strategy in {"vector_only", "hybrid", "hybrid_rerank"} and embedding is None:
                embedding = await embed_with_cache(retrieval_query)
            chunks = await _run_strategy(
                db,
                retrieval_query,
                workspace_ids,
                strategy,
                request.top_k,
                embedding,
                rrf_k=request.rrf_k,
                rerank_top_k=request.rerank_top_k,
            )
            results[strategy] = [_chunk_result(chunk) for chunk in chunks[: request.top_k]]
        except Exception as exc:  # noqa: BLE001 - lab compare should degrade one strategy at a time.
            results[strategy] = []
            errors[strategy] = redact_secrets(str(exc))[:240]
        timing_ms[strategy] = int((time.perf_counter() - started) * 1000)

    return LabCompareResponse(
        results=results,
        overlap_matrix=_overlap_matrix(results),
        timing_ms=timing_ms,
        degraded=bool(errors),
        errors=errors,
        rewriter=_lab_rewriter_info(rewriter_result, used=request.use_rewriter),
    )


async def _run_strategy(
    db: DbSession,
    query: str,
    workspace_ids: list,
    strategy: str,
    top_k: int,
    embedding: list[float] | None,
    *,
    rrf_k: int = 60,
    rerank_top_k: int | None = None,
) -> list[dict]:
    if strategy == "vector_only":
        return await vector_store.search(db, embedding or [], workspace_ids, top_k=top_k)
    if strategy == "keyword_only":
        return await keyword_search.search(db, query, workspace_ids, top_k=top_k)

    vector_results = await vector_store.search(db, embedding or [], workspace_ids, top_k=max(top_k * 2, top_k))
    keyword_results = await keyword_search.search(db, query, workspace_ids, top_k=max(top_k * 2, top_k))
    merged = hybrid.rrf_merge(vector_results, keyword_results, k=rrf_k)
    if strategy == "hybrid":
        return merged[:top_k]
    rerank_output = rerank_top_k if rerank_top_k is not None else top_k
    reranked, _fallback = await reranker.rerank(query, merged, top_k=rerank_output)
    return reranked


def _score(chunk: dict) -> float:
    for key in ("rerank_score", "vector_score", "keyword_score", "rrf_score"):
        value = chunk.get(key)
        if value is not None:
            return float(value)
    return 0.0


def _chunk_result(chunk: dict) -> LabChunkResult:
    return LabChunkResult(
        id=str(chunk.get("chunk_id") or chunk.get("id") or ""),
        chunk_uid=str(chunk.get("chunk_uid") or "") or None,
        score=_score(chunk),
        text=str(chunk.get("content") or ""),
        doc_name=str(chunk.get("document_title") or ""),
        document_id=str(chunk.get("document_id") or "") or None,
        section_path=chunk.get("section_path"),
        page_number=chunk.get("page_number"),
    )


def _overlap_matrix(results: dict[str, list[LabChunkResult]]) -> dict[str, float]:
    matrix: dict[str, float] = {}
    strategy_names = list(results)
    for left_index, left_name in enumerate(strategy_names):
        left_ids = {item.id for item in results[left_name]}
        for right_name in strategy_names[left_index + 1 :]:
            right_ids = {item.id for item in results[right_name]}
            denominator = max(len(left_ids | right_ids), 1)
            matrix[f"{left_name}_vs_{right_name}"] = len(left_ids & right_ids) / denominator
    return matrix


def _resolve_lab_route(request: LabCompareRequest) -> str:
    if request.route_override:
        return request.route_override
    rule_result = _rule_route(request.query)
    if rule_result and rule_result.get("route") in VALID_LAB_ROUTES:
        return str(rule_result["route"])
    return "tech_general"


async def _resolve_lab_rewriter(request: LabCompareRequest, route: str) -> RewriterResult:
    if not request.use_rewriter:
        return RewriterResult(
            original_query=request.query.strip(),
            rewritten_query=request.query.strip(),
            effective_query=request.query.strip(),
            route=route,
            history_used=False,
            fallback_reason="",
            missing_entities=[],
            diagnostic_hint=None,
        )
    return await rewrite_query(
        original_query=request.query,
        route=route,
        key_entities=[],
        recent_turns=[turn.model_dump() for turn in request.recent_turns] if request.recent_turns else None,
        context_summary=request.context_summary,
        use_history=True,
    )


def _lab_rewriter_info(result: RewriterResult, *, used: bool) -> LabRewriterInfo:
    return LabRewriterInfo(
        used=used,
        route=result.route,
        original_query=result.original_query,
        rewritten_query=result.rewritten_query,
        effective_query=result.effective_query,
        fallback_reason=result.fallback_reason,
        missing_entities=result.missing_entities,
        diagnostic_hint=result.diagnostic_hint,
    )

