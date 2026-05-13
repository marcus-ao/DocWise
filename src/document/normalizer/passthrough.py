from __future__ import annotations

from pathlib import Path

from src.document.normalizer import NormalizedDocument, _now_iso


def wrap_plain_text(file_bytes: bytes, file_name: str) -> NormalizedDocument:
    title = Path(file_name).stem.replace("-", " ").replace("_", " ").strip() or file_name
    body = file_bytes.decode("utf-8", errors="replace")
    markdown = f"# {title}\n\n{body}".encode()
    return NormalizedDocument(
        markdown_bytes=markdown,
        original_format="txt",
        normalizer="wrap_plain_text",
        cache_hit=False,
        normalized_at=_now_iso(),
    )
