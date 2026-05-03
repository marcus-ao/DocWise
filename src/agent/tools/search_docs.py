"""search_docs tool — supplementary retrieval via UnifiedRetriever."""
from __future__ import annotations

import structlog

from src.agent.tools.schemas import RetrievedChunkItem, SearchDocsOutput
from src.common.exceptions import ToolExecutionError
from src.db.session import async_session_factory
from src.retrieval.retriever import UnifiedRetriever

logger = structlog.get_logger(__name__)


async def search_docs(
    query: str,
    workspace_ids: list[str] | None = None,
    top_k: int = 5,
) -> dict:
    try:
        async with async_session_factory() as session:
            retriever = UnifiedRetriever(session)
            results = await retriever.retrieve(
                query=query,
                workspace_ids=workspace_ids or [],
                top_k=top_k,
            )

        chunks = [
            RetrievedChunkItem(
                chunk_uid=r.get("chunk_uid", ""),
                content=r.get("content", "")[:500],
                score=r.get("rerank_score", r.get("rrf_score", 0.0)),
                document_title=r.get("document_title", ""),
                section_path=r.get("section_path"),
                workspace_id=r.get("workspace_id", ""),
            )
            for r in results
        ]
        return SearchDocsOutput(chunks=chunks).model_dump()
    except Exception as exc:
        raise ToolExecutionError("search_docs", str(exc)) from exc
