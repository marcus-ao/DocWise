"""Export chunk_uid + metadata from document_chunks table for eval case annotation."""
from __future__ import annotations

import asyncio
import csv
import sys
from pathlib import Path

from sqlalchemy import select

from src.db.session import async_session_factory
from src.models.document import DocumentChunk

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"


async def export_chunk_index(output_path: Path | None = None) -> None:
    if output_path is None:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = OUTPUT_DIR / "chunk_index.csv"

    async with async_session_factory() as session:
        chunks = (
            await session.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.is_active.is_(True))
                .order_by(DocumentChunk.workspace_id, DocumentChunk.chunk_uid)
            )
        ).all()

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "chunk_uid", "document_id", "workspace_id",
            "section_title", "section_path", "doc_type", "language", "token_count",
        ])
        for c in chunks:
            writer.writerow([
                c.chunk_uid,
                str(c.document_id),
                str(c.workspace_id),
                c.section_title or "",
                c.section_path or "",
                c.doc_type.value if c.doc_type else "",
                c.language.value if c.language else "",
                c.token_count,
            ])

    print(f"Exported {len(chunks)} chunks to {output_path}")


def main() -> None:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    asyncio.run(export_chunk_index(output))


if __name__ == "__main__":
    main()
