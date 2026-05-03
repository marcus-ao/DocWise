"""PostgreSQL tsvector/tsquery full-text keyword search."""
from __future__ import annotations

from uuid import UUID

import structlog
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.state import RETRIEVAL_KEYWORD_TOP_K
from src.retrieval.metadata_filter import detect_query_language

logger = structlog.get_logger(__name__)


async def search(
    session: AsyncSession,
    query: str,
    workspace_ids: list[UUID],
    top_k: int = RETRIEVAL_KEYWORD_TOP_K,
) -> list[dict]:
    """Return top-k chunks by ts_rank full-text score.

    Automatically selects 'chinese' or 'english' tsvector config
    based on query language.
    """
    if not workspace_ids or not query.strip():
        return []

    lang = detect_query_language(query)
    ts_config = "chinese" if lang == "zh" else "english"
    sql = text(f"""
        SELECT
            dc.id            AS chunk_id,
            dc.chunk_uid,
            dc.content,
            d.title          AS document_title,
            dc.section_path,
            dc.workspace_id::text,
            dc.page_number,
            dc.doc_type,
            dc.document_id::text,
            ts_rank(dc.content_tsv, plainto_tsquery('{ts_config}', :query)) AS keyword_score
        FROM document_chunks dc
        JOIN documents d ON d.id = dc.document_id
        WHERE dc.content_tsv @@ plainto_tsquery('{ts_config}', :query)
          AND dc.workspace_id IN :workspace_ids
          AND dc.is_active = true
          AND d.status = 'ready'
        ORDER BY keyword_score DESC
        LIMIT :top_k
    """).bindparams(bindparam("workspace_ids", expanding=True))

    result = await session.execute(sql, {"query": query, "workspace_ids": workspace_ids, "top_k": top_k})
    rows = result.mappings().all()

    return [
        {
            "chunk_id": str(r["chunk_id"]),
            "chunk_uid": r["chunk_uid"],
            "content": r["content"],
            "document_title": r["document_title"],
            "section_path": r["section_path"],
            "workspace_id": r["workspace_id"],
            "page_number": r["page_number"],
            "doc_type": str(r["doc_type"]) if r["doc_type"] else None,
            "document_id": r["document_id"],
            "vector_score": None,
            "keyword_score": float(r["keyword_score"]) if r["keyword_score"] is not None else 0.0,
            "rrf_score": 0.0,
        }
        for r in rows
    ]
