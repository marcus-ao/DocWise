from __future__ import annotations

import re

from src.config.entity_patterns import ENTITY_PATTERNS

# Each pattern in ENTITY_PATTERNS carries its own inline flag (e.g. ``(?i)``).
# Do NOT apply a global ``re.IGNORECASE`` flag here — that would turn the
# UPPERCASE-only ``error_code`` matcher into "any 3+ char ASCII word" and the
# critical-entity guard would reject almost every rewrite.
_COMPILED_PATTERNS = {
    key: re.compile(pattern)
    for key, pattern in ENTITY_PATTERNS.items()
}


def normalize_entity(value: str) -> str:
    return value.strip().replace("\\", "/").replace("_", "-").lower()


def extract_regex_entities(query: str) -> list[str]:
    entities: list[str] = []
    for pattern in _COMPILED_PATTERNS.values():
        for match in pattern.findall(query):
            item = match if isinstance(match, str) else next((part for part in match if part), "")
            if item:
                entities.append(item)
    return _dedupe(entities)


def merge_critical_entities(query: str, key_entities: list[str]) -> list[str]:
    merged = extract_regex_entities(query)
    merged.extend(item for item in key_entities if isinstance(item, str) and item.strip())
    return _dedupe(merged)


def missing_critical_entities(rewritten_query: str, critical_entities: list[str]) -> list[str]:
    normalized_query = normalize_entity(rewritten_query)
    missing: list[str] = []
    for entity in critical_entities:
        normalized_entity = normalize_entity(entity)
        if normalized_entity and normalized_entity not in normalized_query:
            missing.append(entity)
    return _dedupe(missing)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        key = normalize_entity(item)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item.strip())
    return deduped
