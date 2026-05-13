"""Format router: supported source formats -> Markdown bytes."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from src.common.exceptions import NonRetryableError

SUPPORTED_EXTS = {".md", ".markdown", ".mdx", ".txt", ".pdf", ".docx", ".doc", ".html", ".htm"}


@dataclass(slots=True)
class NormalizedDocument:
    markdown_bytes: bytes
    original_format: str
    normalizer: str
    cache_hit: bool
    normalized_at: str


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


async def normalize_to_markdown(
    file_bytes: bytes,
    file_name: str,
    content_type: str | None = None,
) -> NormalizedDocument:
    ext = Path(file_name).suffix.lower()
    if ext in {".md", ".markdown", ".mdx"}:
        return NormalizedDocument(
            markdown_bytes=file_bytes,
            original_format=ext.lstrip("."),
            normalizer="passthrough",
            cache_hit=False,
            normalized_at=_now_iso(),
        )
    if ext == ".txt":
        from src.document.normalizer.passthrough import wrap_plain_text

        return wrap_plain_text(file_bytes, file_name)
    if ext in {".pdf", ".docx", ".doc", ".html", ".htm"}:
        from src.document.normalizer.mineru import convert_via_mineru

        return await convert_via_mineru(file_bytes, file_name, content_type)
    raise NonRetryableError(f"unsupported format: {ext or '<none>'}")
