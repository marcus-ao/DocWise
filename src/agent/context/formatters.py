from __future__ import annotations

import json
from math import floor

from src.config.settings import settings
from src.document.chunker import token_count


def estimate_tokens(text: str) -> int:
    return token_count(text)


def safe_budget(budget: int) -> int:
    scaled = floor(budget * settings.context_token_estimate_safety_margin)
    return max(128, scaled)


def shorten_preview(text: str, limit: int = 80) -> str:
    value = " ".join(str(text).split())
    return value[:limit] if len(value) <= limit else value[: limit - 3] + "..."


def to_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        return str(value)


def truncate_text(text: str, max_chars: int) -> tuple[str, int]:
    if max_chars <= 0:
        return "", len(text)
    if len(text) <= max_chars:
        return text, 0
    return text[:max_chars], len(text) - max_chars


def format_retrieval_item(chunk: dict, *, include_content: bool, max_chars: int) -> tuple[str, int]:
    title = str(chunk.get("document_title") or "")
    section = str(chunk.get("section_path") or "")
    score = chunk.get("rerank_score")
    score_text = f"{float(score):.3f}" if isinstance(score, (int, float)) else "n/a"
    prefix = f"{title} > {section} (score={score_text})".strip()
    if not include_content:
        return prefix, 0

    content = to_text(chunk.get("content") or "")
    truncated, dropped = truncate_text(content, max_chars)
    if truncated:
        return f"{prefix}\n{truncated}", dropped
    return prefix, dropped


def format_tool_result_item(result: dict, *, max_chars: int) -> tuple[str, int]:
    tool_name = str(result.get("tool_name") or "tool")
    status = str(result.get("status") or "unknown")
    output = to_text(result.get("output"))
    error = to_text(result.get("error"))
    payload = error or output or "Tool completed"
    truncated, dropped = truncate_text(payload, max_chars)
    return f"{tool_name}: status={status} output={truncated}", dropped
