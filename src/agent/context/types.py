from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict


class SectionPreview(TypedDict):
    section_kind: Literal["system", "query", "retrieval", "tool_result", "summary"]
    item_count: int
    total_chars_before: int
    total_chars_after: int
    token_estimate: int
    items_preview: list[str]


class ContextDiagnostics(TypedDict):
    budget: int
    estimated_prompt_tokens: int
    sections: dict[str, SectionPreview]
    truncations: list[tuple[str, int]]
    compaction_triggered: bool
    compaction_input_tokens: int | None
    compaction_output_tokens: int | None
    fallback_used: bool
    fallback_reason: str | None


@dataclass(slots=True)
class ModelContext:
    messages: list[dict]
    diagnostics: ContextDiagnostics
    preview: dict[str, SectionPreview]
    estimated_prompt_tokens: int
    compaction_summary: str | None = None
