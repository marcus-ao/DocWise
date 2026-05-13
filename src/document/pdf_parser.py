"""PDF parser using PyMuPDF."""
from __future__ import annotations

import asyncio
from pathlib import Path

import fitz

from src.document.parser import ParsedBlock, ParsedDocument

PARSER_NAME = "pymupdf"
PARSER_VERSION = "1.0"


def _parse_pdf_sync(file_bytes: bytes, file_name: str, content_type: str) -> ParsedDocument:
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    try:
        blocks: list[ParsedBlock] = []
        cursor = 0
        page_count = doc.page_count
        for page_index in range(page_count):
            page = doc.load_page(page_index)
            for block in page.get_text("blocks"):
                text = str(block[4]).strip()
                if not text:
                    continue
                start_char = cursor
                end_char = start_char + len(text)
                blocks.append(
                    ParsedBlock(
                        text=text,
                        block_type="paragraph",
                        page_number=page_index + 1,
                        start_char=start_char,
                        end_char=end_char,
                    )
                )
                cursor = end_char + 1
        title = (doc.metadata or {}).get("title") or Path(file_name).stem
    finally:
        doc.close()
    return ParsedDocument(
        title=title,
        file_name=file_name,
        content_type=content_type,
        parser_name=PARSER_NAME,
        parser_version=PARSER_VERSION,
        byte_size=len(file_bytes),
        blocks=blocks,
        metadata={"page_count": page_count},
    )


async def parse_pdf(file_bytes: bytes, file_name: str, content_type: str = "application/pdf") -> ParsedDocument:
    return await asyncio.to_thread(_parse_pdf_sync, file_bytes, file_name, content_type)
