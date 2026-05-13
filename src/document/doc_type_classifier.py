from __future__ import annotations

import re

from src.models.base import DocType

SOP_PATTERNS = [
    re.compile(r"(?:^|[/_\-])troubleshoot(?:ing|er)?(?:[/_.\-]|$)", re.IGNORECASE),
    re.compile(r"(?:^|[/_\-])incidents?(?!(?:[/_\-])?response)", re.IGNORECASE),
]
RUNBOOK_PATTERNS = [
    re.compile(r"(?:^|[/_\-])runbook", re.IGNORECASE),
    re.compile(r"(?:^|[/_\-])sop(?:[/_.\-]|$)", re.IGNORECASE),
    re.compile(r"incident[/_\-]?response", re.IGNORECASE),
]
API_DOC_PATTERNS = [
    re.compile(r"(?:^|[/_\-])api(?:[/_.\-]|$)", re.IGNORECASE),
    re.compile(r"(?:^|[/_\-])reference(?:[/_.\-]|$)", re.IGNORECASE),
    re.compile(r"openapi", re.IGNORECASE),
    re.compile(r"swagger", re.IGNORECASE),
]


def classify_doc_type(relative_path: str) -> DocType:
    normalized = relative_path.replace("\\", "/")
    if any(pattern.search(normalized) for pattern in RUNBOOK_PATTERNS):
        return DocType.runbook
    if any(pattern.search(normalized) for pattern in SOP_PATTERNS):
        return DocType.sop
    if any(pattern.search(normalized) for pattern in API_DOC_PATTERNS):
        return DocType.api_doc
    return DocType.tech_doc
