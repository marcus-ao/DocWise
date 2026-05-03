"""PgVectorStore — cosine similarity search over document_chunks."""
from __future__ import annotations

from uuid import UUID

import structlog
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.state import RETRIEVAL_VECTOR_TOP_K

logger = structlog.get_logger(__name__)


async def search(
    session: AsyncSession,
    embedding: list[float],
    workspace_ids: list[UUID],
    top_k: int = RETRIEVAL_VECTOR_TOP_K,
) -> list[dict]:
    """Return top-k chunks by cosine similarity from pgvector.

    Each result dict contains: chunk_id, chunk_uid, content,
    document_title, section_path, workspace_id, page_number,
    doc_type, vector_score.
    """
    if not workspace_ids or not embedding:
        return []

    embedding_literal = "[" + ",".join(str(v) for v in embedding) + "]"
    query = text("""
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
            1 - ((dc.embedding::halfvec(2048)) <=> (:embedding)::halfvec(2048)) AS vector_score
        FROM document_chunks dc
        JOIN documents d ON d.id = dc.document_id
        WHERE dc.workspace_id IN :workspace_ids
          AND dc.is_active = true
          AND dc.embedding IS NOT NULL
          AND d.status = 'ready'
        ORDER BY (dc.embedding::halfvec(2048)) <=> (:embedding)::halfvec(2048)
        LIMIT :top_k
    """).bindparams(bindparam("workspace_ids", expanding=True))

    result = await session.execute(
        query,
        {"embedding": embedding_literal, "workspace_ids": workspace_ids, "top_k": top_k},
    )
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
            "vector_score": float(r["vector_score"]) if r["vector_score"] is not None else 0.0,
            "keyword_score": None,
            "rrf_score": 0.0,
        }
        for r in rows
    ]
