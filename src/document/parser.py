"""Unified document parser contracts and dispatch."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
LARGE_DOCUMENT_THRESHOLD_BYTES = 30 * 1024


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
    byte_size: int = 0
    blocks: list[ParsedBlock]
    metadata: dict = Field(default_factory=dict)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", value.strip().lower()).strip("-")
    return slug or "section"


def _is_h1_heading(block: ParsedBlock) -> bool:
    return block.block_type == "heading" and block.heading_level == 1 and bool(block.text.strip())


def _group_by_h1(blocks: list[ParsedBlock]) -> list[tuple[str, list[ParsedBlock]]]:
    # Buffer leading blocks until the first H1. If no H1 ever appears we
    # intentionally return an empty list and let the caller keep the original
    # ParsedDocument unsplit, so the preamble content is never discarded.
    preamble: list[ParsedBlock] = []
    groups: list[tuple[str, list[ParsedBlock]]] = []
    current_heading: str | None = None
    current_blocks: list[ParsedBlock] = []

    for block in blocks:
        block_copy = block.model_copy(deep=True)
        if _is_h1_heading(block_copy):
            if current_heading is None:
                current_heading = block_copy.text.strip()
                current_blocks = [*preamble, block_copy]
                preamble = []
                continue

            groups.append((current_heading, current_blocks))
            current_heading = block_copy.text.strip()
            current_blocks = [block_copy]
            continue

        if current_heading is None:
            preamble.append(block_copy)
        else:
            current_blocks.append(block_copy)

    if current_heading is not None:
        groups.append((current_heading, current_blocks))

    return groups


def _render_block_markdown(block: ParsedBlock) -> str:
    text = block.text.strip()
    if not text:
        return ""
    if block.block_type == "heading":
        level = block.heading_level or 1
        return f"{'#' * level} {text}"
    if block.block_type == "code":
        return f"```\n{text}\n```"
    return text


def render_parsed_document_bytes(parsed: ParsedDocument) -> bytes:
    parts = [_render_block_markdown(block) for block in parsed.blocks]
    markdown = "\n\n".join(part for part in parts if part).strip()
    return markdown.encode("utf-8")


def split_large_document(parsed: ParsedDocument) -> list[ParsedDocument]:
    if parsed.byte_size < LARGE_DOCUMENT_THRESHOLD_BYTES:
        return [parsed]

    h1_groups = _group_by_h1(parsed.blocks)
    if len(h1_groups) <= 1:
        logger.warning(
            "Large document %s (%s bytes) was not split because it has %s H1 section(s)",
            parsed.file_name,
            parsed.byte_size,
            len(h1_groups),
        )
        return [parsed]

    seen_slugs: dict[str, int] = {}
    split_documents: list[ParsedDocument] = []
    for h1_text, group_blocks in h1_groups:
        base_slug = _slugify(h1_text)
        count = seen_slugs.get(base_slug, 0)
        slug = base_slug if count == 0 else f"{base_slug}-{count + 1}"
        seen_slugs[base_slug] = count + 1

        child = ParsedDocument(
            title=f"{parsed.title} — {h1_text}",
            file_name=f"{parsed.file_name}#{slug}",
            content_type=parsed.content_type,
            parser_name=parsed.parser_name,
            parser_version=parsed.parser_version,
            byte_size=0,
            blocks=group_blocks,
            metadata={
                # Children inherit the parent's parse metadata, including any
                # normalizer facts, so ingestion can rewrite provenance without
                # recomputing normalization details per child section.
                **parsed.metadata,
                "h1_slug": slug,
            },
        )
        # Child byte_size is based on the rendered markdown subsection rather
        # than a raw-file byte slice because the split is logical, not a direct
        # offset range into the original uploaded object.
        child.byte_size = len(render_parsed_document_bytes(child))
        split_documents.append(child)

    return split_documents


def infer_content_type(file_name: str, content_type: str | None = None) -> str:
    if content_type and content_type != "application/octet-stream":
        return content_type
    suffix = Path(file_name).suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix == ".doc":
        return "application/msword"
    if suffix == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if suffix in {".md", ".markdown", ".mdx"}:
        return "text/markdown"
    if suffix == ".txt":
        return "text/plain"
    if suffix in {".html", ".htm"}:
        return "text/html"
    return content_type or "application/octet-stream"


async def parse_document_bytes(
    file_bytes: bytes,
    file_name: str,
    content_type: str | None = None,
) -> ParsedDocument:
    from src.document.markdown_parser import parse_markdown
    from src.document.normalizer import SUPPORTED_EXTS, normalize_to_markdown

    ext = Path(file_name).suffix.lower()
    inferred_type = infer_content_type(file_name, content_type)
    if ext not in SUPPORTED_EXTS:
        raise ValueError(f"Unsupported content type for {file_name}: {inferred_type}")

    normalized = await normalize_to_markdown(file_bytes, file_name, inferred_type)
    parsed = await parse_markdown(normalized.markdown_bytes, file_name, "text/markdown")
    parsed.metadata["normalizer"] = {
        "original_format": normalized.original_format,
        "tool": normalized.normalizer,
        "cache_hit": normalized.cache_hit,
        "normalized_at": normalized.normalized_at,
    }
    parsed.byte_size = len(file_bytes)
    return parsed
