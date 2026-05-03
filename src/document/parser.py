"""Unified document parser contracts and dispatch."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class ParsedBlock(BaseModel):
    text: str
    block_type: Literal["heading", "paragraph", "code", "table"] = "paragraph"
    page_number: int | None = None
    heading_level: int | None = None
    section_path: str | None = None
    source_anchor: str | None = None
    contains_code: bool = False
    start_char: int | None = None
    end_char: int | None = None
    metadata: dict = Field(default_factory=dict)


class ParsedDocument(BaseModel):
    title: str
    file_name: str
    content_type: str
    parser_name: str
    parser_version: str
    blocks: list[ParsedBlock]
    metadata: dict = Field(default_factory=dict)


def infer_content_type(file_name: str, content_type: str | None = None) -> str:
    if content_type and content_type != "application/octet-stream":
        return content_type
    suffix = Path(file_name).suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if suffix in {".md", ".markdown"}:
        return "text/markdown"
    if suffix == ".txt":
        return "text/plain"
    return content_type or "application/octet-stream"


async def parse_document_bytes(
    file_bytes: bytes,
    file_name: str,
    content_type: str | None = None,
) -> ParsedDocument:
    inferred_type = infer_content_type(file_name, content_type)

    if inferred_type == "application/pdf" or file_name.lower().endswith(".pdf"):
        from src.document.pdf_parser import parse_pdf

        return await parse_pdf(file_bytes, file_name, inferred_type)
    if inferred_type.endswith("wordprocessingml.document") or file_name.lower().endswith(".docx"):
        from src.document.docx_parser import parse_docx

        return await parse_docx(file_bytes, file_name, inferred_type)
    if inferred_type in {"text/markdown", "text/plain"} or file_name.lower().endswith((".md", ".markdown", ".txt")):
        from src.document.markdown_parser import parse_markdown

        return await parse_markdown(file_bytes, file_name, inferred_type)

    raise ValueError(f"Unsupported content type for {file_name}: {inferred_type}")
