"""Helpers for serialising citations from live Agent state or persisted traces."""

from __future__ import annotations

from uuid import UUID, uuid4

from src.schemas.shared import CitationItem


def _uuid_or_random(value: object) -> UUID:
    try:
        if value:
            return UUID(str(value))
    except ValueError:
        pass
    return uuid4()


def citation_from_dict(item: dict) -> CitationItem:
    return CitationItem(
        chunk_id=_uuid_or_random(item.get("chunk_id")),
        chunk_uid=str(item.get("chunk_uid") or ""),
        document_id=_uuid_or_random(item.get("document_id")),
        document_title=str(item.get("document_title") or ""),
        section_path=item.get("section_path"),
        page_number=item.get("page_number"),
        score=float(item.get("score") or item.get("rerank_score") or item.get("rrf_score") or 0.0),
        quote=str(item.get("quote") or ""),
    )


def citations_from_final(final_citations: list | None) -> list[CitationItem]:
    if not final_citations:
        return []
    seen: set[tuple[str, str, str]] = set()
    citations: list[CitationItem] = []
    for item in final_citations:
        if not isinstance(item, dict):
            continue
        citation = citation_from_dict(item)
        dedupe_key = (
            str(citation.chunk_id),
            citation.chunk_uid,
            citation.quote,
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        citations.append(citation)
    return citations


def citations_from_retrieval_rows(rows: list, limit: int = 5) -> list[CitationItem]:
    return [
        CitationItem(
            chunk_id=row.chunk_id,
            chunk_uid=row.chunk_uid,
            document_id=row.document_id,
            document_title="",
            section_path=None,
            page_number=None,
            score=float(row.rerank_score or row.rrf_score or 0.0),
            quote="",
        )
        for row in rows[:limit]
    ]
