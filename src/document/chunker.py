"""Document chunking helpers for ingestion and retrieval evidence."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from functools import lru_cache

from src.models.base import ChunkLanguage

from .parser import ParsedBlock, ParsedDocument

DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 120
DEFAULT_MIN_CHUNK_SIZE = 40
DEFAULT_MAX_CHUNK_SIZE = 900


@dataclass(slots=True)
class ChunkDraft:
    chunk_uid: str
    chunk_index: int
    content: str
    content_hash: str
    token_count: int
    char_count: int
    section_title: str | None
    section_path: str | None
    heading_level: int | None
    page_number: int | None
    start_char: int | None
    end_char: int | None
    source_anchor: str | None
    language: ChunkLanguage
    metadata: dict = field(default_factory=dict)


@lru_cache(maxsize=1)
def _encoding():
    try:
        import tiktoken  # type: ignore[import-not-found]

        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


def _slug(value: str | None) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", value).strip("-")
    return value or "section"


def _tokenize(text: str) -> list[str]:
    encoding = _encoding()
    if encoding is not None:
        return [str(token) for token in encoding.encode(text)]
    return re.findall(r"\S+", text)


def _token_count(text: str) -> int:
    return len(_tokenize(text))


def token_count(text: str) -> int:
    """Public alias for token estimation used by context runtime and other modules."""
    return _token_count(text)


def _split_words_with_overlap(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    words = re.findall(r"\S+", text)
    if not words:
        return []
    if len(words) <= chunk_size:
        return [" ".join(words)]

    step = max(1, chunk_size - chunk_overlap)
    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(len(words), start + chunk_size)
        if chunks and end == len(words) and start < len(words) and words[start:end] == chunks[-1].split():
            break
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start += step
    return chunks


def _split_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    encoding = _encoding()
    if encoding is None:
        return _split_words_with_overlap(text, chunk_size, chunk_overlap)

    tokens = encoding.encode(text)
    if len(tokens) <= chunk_size:
        return [text.strip()] if text.strip() else []
    step = max(1, chunk_size - chunk_overlap)
    chunks: list[str] = []
    start = 0
    while start < len(tokens):
        end = min(len(tokens), start + chunk_size)
        chunk = encoding.decode(tokens[start:end]).strip()
        if chunk and (not chunks or chunk != chunks[-1]):
            chunks.append(chunk)
        if end == len(tokens):
            break
        start += step
    return chunks


def detect_language(text: str) -> str:
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin_words = len(re.findall(r"[A-Za-z]+", text))
    if chinese_chars and latin_words:
        return "mixed"
    if chinese_chars:
        return "zh"
    return "en"


def generate_chunk_uid(document_title: str, section_title: str | None, content: str) -> str:
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    return f"{_slug(document_title)}:{_slug(section_title)}:{digest}"


def _section_title(block: ParsedBlock) -> str | None:
    if block.section_path:
        return block.section_path.split(">")[-1].strip()
    return None


def _section_key(block: ParsedBlock, fallback_title: str) -> tuple[str, str | None]:
    section_path = block.section_path or fallback_title
    source_anchor = block.source_anchor or _slug(_section_title(block) or section_path)
    return section_path, source_anchor


def _merge_metadata(blocks: list[ParsedBlock]) -> dict:
    metadata: dict = {}
    for block in blocks:
        metadata.update(block.metadata or {})
    metadata["block_types"] = sorted({block.block_type for block in blocks})
    metadata["contains_code"] = any(block.contains_code or block.block_type == "code" for block in blocks)
    return metadata


def _draft_from_text(
    *,
    document: ParsedDocument,
    blocks: list[ParsedBlock],
    content: str,
    chunk_index: int,
    ordinal: int,
) -> ChunkDraft:
    first = blocks[0]
    section_path, source_anchor = _section_key(first, document.title)
    section_title = _section_title(first) or section_path
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    token_count = _token_count(content)
    uid_content = f"{ordinal}:{content}"
    return ChunkDraft(
        chunk_uid=generate_chunk_uid(document.title, source_anchor or section_title, uid_content),
        chunk_index=chunk_index,
        content=content,
        content_hash=content_hash,
        token_count=token_count,
        char_count=len(content),
        section_title=section_title,
        section_path=section_path,
        heading_level=first.heading_level,
        page_number=first.page_number,
        start_char=min((b.start_char for b in blocks if b.start_char is not None), default=None),
        end_char=max((b.end_char for b in blocks if b.end_char is not None), default=None),
        source_anchor=source_anchor,
        language=ChunkLanguage(detect_language(content)),
        metadata=_merge_metadata(blocks),
    )


def _flush_group(
    *,
    document: ParsedDocument,
    group: list[ParsedBlock],
    chunk_index: int,
    chunk_size: int,
    chunk_overlap: int,
    min_chunk_size: int,
) -> tuple[list[ChunkDraft], int]:
    if not group:
        return [], chunk_index
    text = "\n\n".join(block.text.strip() for block in group if block.text.strip()).strip()
    if not text:
        return [], chunk_index

    parts = _split_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    drafts: list[ChunkDraft] = []
    for part in parts:
        if _token_count(part) < min_chunk_size and drafts:
            previous = drafts[-1]
            previous.content = f"{previous.content}\n\n{part}".strip()
            previous.content_hash = hashlib.sha256(previous.content.encode("utf-8")).hexdigest()
            previous.token_count = _token_count(previous.content)
            previous.char_count = len(previous.content)
            continue
        drafts.append(
            _draft_from_text(
                document=document,
                blocks=group,
                content=part,
                chunk_index=chunk_index,
                ordinal=len(drafts),
            )
        )
        chunk_index += 1
    return drafts, chunk_index


def chunk_document(
    document: ParsedDocument,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    min_chunk_size: int = DEFAULT_MIN_CHUNK_SIZE,
    max_chunk_size: int = DEFAULT_MAX_CHUNK_SIZE,
) -> list[ChunkDraft]:
    effective_size = min(chunk_size, max_chunk_size)
    effective_overlap = min(chunk_overlap, max(0, effective_size - 1))
    chunks: list[ChunkDraft] = []
    group: list[ParsedBlock] = []
    current_section: str | None = None
    chunk_index = 0

    for block in document.blocks:
        if not block.text.strip():
            continue
        if block.block_type == "heading":
            current_section = block.section_path or block.text.strip()
            continue

        section_path = block.section_path or current_section or document.title
        if group and (group[0].section_path or document.title) != section_path:
            new_chunks, chunk_index = _flush_group(
                document=document,
                group=group,
                chunk_index=chunk_index,
                chunk_size=effective_size,
                chunk_overlap=effective_overlap,
                min_chunk_size=min_chunk_size,
            )
            chunks.extend(new_chunks)
            group = []

        if block.section_path is None:
            block = block.model_copy(update={"section_path": section_path})
        group.append(block)

    new_chunks, _ = _flush_group(
        document=document,
        group=group,
        chunk_index=chunk_index,
        chunk_size=effective_size,
        chunk_overlap=effective_overlap,
        min_chunk_size=min_chunk_size,
    )
    chunks.extend(new_chunks)
    return chunks
