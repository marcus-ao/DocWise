"""Markdown and plain-text parser preserving heading paths."""
from __future__ import annotations

import re
from pathlib import Path

from src.document.parser import ParsedBlock, ParsedDocument

PARSER_NAME = "markdown_parser"
PARSER_VERSION = "1.0"


def _anchor(text: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", text.strip().lower()).strip("-")
    return value or "section"


def _flush_paragraph(
    lines: list[str],
    blocks: list[ParsedBlock],
    section_stack: list[str],
    source_anchor: str | None,
    cursor: int,
) -> int:
    if not lines:
        return cursor
    text = "\n".join(lines).strip()
    if text:
        start_char = cursor
        end_char = start_char + len(text)
        blocks.append(
            ParsedBlock(
                text=text,
                block_type="paragraph",
                section_path=" > ".join(section_stack) or None,
                source_anchor=source_anchor,
                start_char=start_char,
                end_char=end_char,
            )
        )
        cursor = end_char + 1
    lines.clear()
    return cursor


async def parse_markdown(file_bytes: bytes, file_name: str, content_type: str = "text/markdown") -> ParsedDocument:
    text = file_bytes.decode("utf-8", errors="replace")
    title = Path(file_name).stem.replace("-", " ").replace("_", " ").strip() or file_name
    blocks: list[ParsedBlock] = []
    section_stack: list[str] = []
    paragraph_lines: list[str] = []
    code_lines: list[str] = []
    in_code = False
    current_anchor: str | None = None
    cursor = 0

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.strip().startswith("```"):
            cursor = _flush_paragraph(paragraph_lines, blocks, section_stack, current_anchor, cursor)
            if in_code:
                code_text = "\n".join(code_lines).strip("\n")
                if code_text:
                    start_char = cursor
                    end_char = start_char + len(code_text)
                    blocks.append(
                        ParsedBlock(
                            text=code_text,
                            block_type="code",
                            section_path=" > ".join(section_stack) or None,
                            source_anchor=current_anchor,
                            contains_code=True,
                            start_char=start_char,
                            end_char=end_char,
                        )
                    )
                    cursor = end_char + 1
                code_lines.clear()
                in_code = False
            else:
                in_code = True
            continue

        if in_code:
            code_lines.append(raw_line)
            continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            cursor = _flush_paragraph(paragraph_lines, blocks, section_stack, current_anchor, cursor)
            level = len(heading.group(1))
            heading_text = heading.group(2).strip()
            section_stack = section_stack[: level - 1]
            section_stack.append(heading_text)
            current_anchor = _anchor(heading_text)
            blocks.append(
                ParsedBlock(
                    text=heading_text,
                    block_type="heading",
                    heading_level=level,
                    section_path=" > ".join(section_stack),
                    source_anchor=current_anchor,
                )
            )
            continue

        if not line.strip():
            cursor = _flush_paragraph(paragraph_lines, blocks, section_stack, current_anchor, cursor)
            continue

        paragraph_lines.append(line)

    _flush_paragraph(paragraph_lines, blocks, section_stack, current_anchor, cursor)

    return ParsedDocument(
        title=title,
        file_name=file_name,
        content_type=content_type,
        parser_name=PARSER_NAME,
        parser_version=PARSER_VERSION,
        blocks=blocks,
        metadata={"line_count": len(text.splitlines())},
    )
