"""Export active chunk metadata for eval case annotation and remapping."""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from src.db.session import async_session_factory
from src.models.document import Document, DocumentChunk
from src.models.workspace import Workspace

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "eval"
CSV_HEADERS = [
    "chunk_uid",
    "document_id",
    "workspace_id",
    "section_title",
    "section_path",
    "doc_type",
    "language",
    "token_count",
]


def _default_output_path(output_format: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR / f"chunk_index.{output_format}"


def _serialize_chunk_index_row(
    chunk: DocumentChunk,
    document: Document,
    workspace: Workspace,
) -> dict[str, Any]:
    return {
        "chunk_uid": chunk.chunk_uid,
        "chunk_id": str(chunk.id),
        "document_id": str(document.id),
        "document_title": document.title,
        "workspace_slug": workspace.slug,
        "section_path": chunk.section_path or "",
        "doc_type": document.doc_type.value if document.doc_type else "",
        "language": chunk.language.value if chunk.language else "",
        "token_count": chunk.token_count,
        "is_active": bool(chunk.is_active),
        "parent_document_id": str(document.parent_document_id) if document.parent_document_id else None,
        "provenance": document.provenance or {},
    }


def _serialize_csv_row(
    chunk: DocumentChunk,
    document: Document,
) -> list[str | int]:
    return [
        chunk.chunk_uid,
        str(document.id),
        str(document.workspace_id),
        chunk.section_title or "",
        chunk.section_path or "",
        document.doc_type.value if document.doc_type else "",
        chunk.language.value if chunk.language else "",
        chunk.token_count,
    ]


async def _load_active_chunks(workspace_slug: str | None = None) -> list[tuple[DocumentChunk, Document, Workspace]]:
    async with async_session_factory() as session:
        stmt = (
            select(DocumentChunk, Document, Workspace)
            .join(Document, Document.id == DocumentChunk.document_id)
            .join(Workspace, Workspace.id == Document.workspace_id)
            .where(DocumentChunk.is_active.is_(True))
            .order_by(Workspace.slug, DocumentChunk.chunk_uid)
        )
        if workspace_slug:
            stmt = stmt.where(Workspace.slug == workspace_slug)
        return list((await session.execute(stmt)).all())


async def export_chunk_index(
    output_path: Path | None = None,
    *,
    output_format: str = "json",
    workspace_slug: str | None = None,
) -> Path:
    if output_format not in {"json", "csv"}:
        raise ValueError(f"Unsupported format: {output_format}")

    resolved_output_path = output_path or _default_output_path(output_format)
    resolved_output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = await _load_active_chunks(workspace_slug)

    if output_format == "json":
        payload = [_serialize_chunk_index_row(chunk, document, workspace) for chunk, document, workspace in rows]
        resolved_output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    else:
        with resolved_output_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(CSV_HEADERS)
            for chunk, document, _workspace in rows:
                writer.writerow(_serialize_csv_row(chunk, document))

    print(f"Exported {len(rows)} chunks to {resolved_output_path}")
    return resolved_output_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export active chunk metadata for eval remapping.")
    parser.add_argument("legacy_output", nargs="?", help="Deprecated positional output path.")
    parser.add_argument("-o", "--output", help="Explicit output path.")
    parser.add_argument("--format", choices=("json", "csv"), default="json", help="Output format.")
    parser.add_argument("--workspace", help="Optional workspace slug filter.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output_value = args.output or args.legacy_output
    output_path = Path(output_value) if output_value else None
    asyncio.run(
        export_chunk_index(
            output_path=output_path,
            output_format=args.format,
            workspace_slug=args.workspace,
        )
    )


if __name__ == "__main__":
    main()
