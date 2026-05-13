from __future__ import annotations

import re

_LEADING_NOISE = re.compile(r"^(?:[-*]\s*|改写后(?:的)?(?:检索)?query[:：]?\s*|query[:：]?\s*)", re.IGNORECASE)
_SURROUNDING_QUOTES = "\"'`“”‘’"


def normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def normalize_for_compare(text: str) -> str:
    return normalize_spaces(text).lower().replace("_", "-")


def clean_rewriter_output(text: str) -> str:
    cleaned = text.strip()
    cleaned = _LEADING_NOISE.sub("", cleaned)
    cleaned = cleaned.strip(_SURROUNDING_QUOTES).strip()
    return normalize_spaces(cleaned)
