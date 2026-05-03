"""UnifiedRetriever — convenience entry point for CLI, eval, and tests."""
from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.state import RERANK_TOP_K, RETRIEVAL_KEYWORD_TOP_K, RETRIEVAL_VECTOR_TOP_K
from src.document.embedder import embed_with_cache
from src.retrieval import hybrid, keyword_search, reranker, vector_store
from src.retrieval.metadata_filter import resolve_workspace_ids

logger = structlog.get_logger(__name__)


class UnifiedRetriever:
    """One-shot retrieve: embed → vector → keyword → RRF → rerank."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def retrieve(
        self,
        query: str,
        workspace_ids: list[str],
        top_k: int = RERANK_TOP_K,
    ) -> list[dict]:
        uuids = await resolve_workspace_ids(self._session, workspace_ids)
        if not uuids:
            return []

        vector_results: list[dict] = []
        try:
            query_embedding = await embed_with_cache(query)
            vector_results = await vector_store.search(
                self._session, query_embedding, uuids, top_k=RETRIEVAL_VECTOR_TOP_K,
            )
        except Exception as exc:
            logger.warning("unified_retriever_vector_failed_keyword_fallback", error=str(exc))
        kw_results = await keyword_search.search(
            self._session, query, uuids, top_k=RETRIEVAL_KEYWORD_TOP_K,
        )

        if not vector_results:
            for chunk in kw_results:
                chunk["rrf_score"] = chunk.get("keyword_score", 0.0)
            merged = kw_results
        else:
            merged = hybrid.rrf_merge(vector_results, kw_results)
        reranked, _fallback = await reranker.rerank(query, merged, top_k=top_k)
        return reranked
