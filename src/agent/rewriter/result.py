from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RewriterResult:
    original_query: str
    rewritten_query: str
    effective_query: str
    route: str
    history_used: bool
    fallback_reason: str
    missing_entities: list[str] = field(default_factory=list)
    diagnostic_hint: str | None = None
