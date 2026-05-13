from __future__ import annotations

import asyncio
import hashlib
import html
import io
import json
import re
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
import structlog

from src.common.exceptions import NonRetryableError, RetryableError
from src.config.settings import settings
from src.document.docx_parser import parse_docx
from src.document.normalizer import NormalizedDocument, _now_iso
from src.document.parser import ParsedDocument
from src.document.pdf_parser import parse_pdf

logger = structlog.get_logger(__name__)

# Daily-scoped call counter so long-running workers don't accumulate across days.
# Keyed by ISO date; resets automatically at UTC midnight. Addresses Phase B review MEDIUM #4
# ("_MINERU_CALL_COUNT 全局计数器永不重置").
_MINERU_CALL_STATE: dict[str, object] = {"date": None, "count": 0}

# Formats for which a local fallback parser is available when MinerU is unreachable.
_LOCAL_FALLBACK_FORMATS: frozenset[str] = frozenset({".pdf", ".docx", ".html", ".htm"})
_POLLING_STATES: frozenset[str] = frozenset({"waiting-file", "pending", "running", "converting"})


async def convert_via_mineru(
    file_bytes: bytes,
    file_name: str,
    content_type: str | None = None,
) -> NormalizedDocument:
    ext = Path(file_name).suffix.lower()
    content_hash = hashlib.sha256(file_bytes).hexdigest()
    cache_path, meta_path = _cache_paths(content_hash)
    cached = await _read_cache(cache_path, meta_path, ext)
    if cached is not None:
        return cached

    try:
        if not settings.mineru_api_key:
            raise RetryableError("MinerU API key is not configured", backoff_seconds=1.0)

        markdown_bytes = await _fetch_markdown_via_mineru(file_bytes, file_name, content_type)
        normalized = NormalizedDocument(
            markdown_bytes=markdown_bytes,
            original_format=ext.lstrip("."),
            normalizer="mineru",
            cache_hit=False,
            normalized_at=_now_iso(),
        )
        await _write_cache(cache_path, meta_path, normalized)
        return normalized
    except RetryableError as exc:
        if not settings.normalizer_enable_fallback:
            raise
        if ext in _LOCAL_FALLBACK_FORMATS:
            normalized = await _convert_via_local_fallback(file_bytes, file_name, content_type, ext)
            await _write_cache(cache_path, meta_path, normalized)
            return normalized
        if ext == ".doc":
            # Legacy Word binary format: no local fallback available (python-docx only handles .docx).
            raise NonRetryableError("Local fallback is not supported for .doc files") from exc
        raise NonRetryableError(
            f"MinerU normalization failed for {ext} and no local fallback is available"
        ) from exc


def _cache_paths(content_hash: str) -> tuple[Path, Path]:
    root = Path(settings.normalizer_cache_dir)
    folder = root / content_hash[:2]
    return folder / f"{content_hash}.md", folder / f"{content_hash}.json"


async def _read_cache(cache_path: Path, meta_path: Path, ext: str) -> NormalizedDocument | None:
    if not cache_path.exists():
        return None
    markdown_bytes = await asyncio.to_thread(cache_path.read_bytes)
    normalizer = "mineru"
    normalized_at = _now_iso()
    if meta_path.exists():
        payload = json.loads(await asyncio.to_thread(meta_path.read_text, encoding="utf-8"))
        normalizer = str(payload.get("normalizer") or normalizer)
        normalized_at = str(payload.get("normalized_at") or normalized_at)
    return NormalizedDocument(
        markdown_bytes=markdown_bytes,
        original_format=ext.lstrip("."),
        normalizer=normalizer,
        cache_hit=True,
        normalized_at=normalized_at,
    )


async def _write_cache(cache_path: Path, meta_path: Path, normalized: NormalizedDocument) -> None:
    await asyncio.to_thread(cache_path.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(cache_path.write_bytes, normalized.markdown_bytes)
    meta_payload = {
        "original_format": normalized.original_format,
        "normalizer": normalized.normalizer,
        "normalized_at": normalized.normalized_at,
    }
    await asyncio.to_thread(meta_path.write_text, json.dumps(meta_payload, ensure_ascii=False), "utf-8")


def _bump_call_count() -> int:
    """Increment the daily-scoped MinerU call counter. Resets at UTC date rollover."""
    today = datetime.now(UTC).date().isoformat()
    if _MINERU_CALL_STATE.get("date") != today:
        _MINERU_CALL_STATE["date"] = today
        _MINERU_CALL_STATE["count"] = 0
    count = int(_MINERU_CALL_STATE.get("count", 0)) + 1
    _MINERU_CALL_STATE["count"] = count
    return count


def _reset_call_count_for_testing() -> None:
    """Test hook: reset the counter without waiting for date rollover."""
    _MINERU_CALL_STATE["date"] = None
    _MINERU_CALL_STATE["count"] = 0


async def _fetch_markdown_via_mineru(
    file_bytes: bytes,
    file_name: str,
    content_type: str | None,
) -> bytes:
    timeout = httpx.Timeout(settings.mineru_request_timeout)
    base_url = settings.mineru_api_base_url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {settings.mineru_api_key}",
        "Content-Type": "application/json",
    }
    ext = Path(file_name).suffix.lower()
    data_id = hashlib.sha256(file_bytes).hexdigest()

    count = _bump_call_count()
    if count > settings.mineru_daily_call_budget:
        logger.warning(
            "mineru_daily_call_budget_exceeded",
            call_count=count,
            budget=settings.mineru_daily_call_budget,
            scope_date=_MINERU_CALL_STATE.get("date"),
        )

    # Overall deadline spans BOTH the initial POST and the subsequent polling loop.
    # This fixes Phase B review MEDIUM #3: previously the deadline was set AFTER the
    # POST, so a slow upload could push total elapsed time past mineru_request_timeout.
    deadline = time.monotonic() + settings.mineru_request_timeout

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if time.monotonic() >= deadline:
                raise RetryableError("MinerU deadline reached before POST", backoff_seconds=5.0)
            upload_response = await client.post(
                f"{base_url}/file-urls/batch",
                headers=headers,
                json={
                    "files": [{"name": Path(file_name).name, "data_id": data_id}],
                    "model_version": _model_version_for_extension(ext),
                },
            )
            upload_response.raise_for_status()
            upload_payload = upload_response.json()
            _ensure_success_payload(upload_payload, stage="request_upload_url")
            batch_id, file_url = _extract_batch_upload_target(upload_payload)
            if not batch_id or not file_url:
                raise NonRetryableError("MinerU upload-url response did not include batch_id/file_url")

            put_response = await client.put(file_url, content=file_bytes)
            put_response.raise_for_status()

            while True:
                if time.monotonic() >= deadline:
                    raise RetryableError("MinerU poll timed out", backoff_seconds=5.0)

                poll_response = await client.get(f"{base_url}/extract-results/batch/{batch_id}", headers=headers)
                poll_response.raise_for_status()
                payload = poll_response.json()
                _ensure_success_payload(payload, stage="poll_batch_result")
                result = _extract_batch_result(payload, data_id=data_id, file_name=file_name)
                if result is None:
                    await asyncio.sleep(settings.mineru_poll_interval)
                    continue

                status = str(result.get("state") or "").lower()
                if status == "done":
                    full_zip_url = str(result.get("full_zip_url") or "").strip()
                    if not full_zip_url:
                        raise NonRetryableError("MinerU done result did not include full_zip_url")
                    result_response = await client.get(full_zip_url)
                    result_response.raise_for_status()
                    return _extract_markdown_from_zip(result_response.content)
                if status in {"failed", "error", "cancelled"}:
                    detail = str(result.get("err_msg") or payload.get("msg") or f"state={status}")
                    raise NonRetryableError(f"MinerU task failed: {detail}")
                if status not in _POLLING_STATES:
                    raise NonRetryableError(f"MinerU task returned unknown state={status!r}")

                await asyncio.sleep(settings.mineru_poll_interval)
    except httpx.TimeoutException as exc:
        raise RetryableError(f"MinerU request timed out: {exc}", backoff_seconds=5.0) from exc
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        if status_code == 429 or status_code >= 500:
            raise RetryableError(f"MinerU request failed with status={status_code}", backoff_seconds=5.0) from exc
        raise NonRetryableError(f"MinerU request failed with status={status_code}") from exc
    except httpx.HTTPError as exc:
        raise RetryableError(f"MinerU request failed: {exc}", backoff_seconds=5.0) from exc


def _model_version_for_extension(ext: str) -> str:
    if ext in {".html", ".htm"}:
        return "MinerU-HTML"
    return "vlm"


def _ensure_success_payload(payload: dict, *, stage: str) -> None:
    code = payload.get("code")
    if code in {None, 0}:
        return
    raise NonRetryableError(f"MinerU {stage} failed with code={code}: {payload.get('msg') or 'unknown error'}")


def _extract_batch_upload_target(payload: dict) -> tuple[str | None, str | None]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return None, None
    batch_id = str(data.get("batch_id") or "") or None
    file_urls = data.get("file_urls")
    if isinstance(file_urls, list) and file_urls:
        return batch_id, str(file_urls[0])
    return batch_id, None


def _extract_batch_result(payload: dict, *, data_id: str, file_name: str) -> dict | None:
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    extract_result = data.get("extract_result")
    if not isinstance(extract_result, list):
        return None
    normalized_name = Path(file_name).name
    for item in extract_result:
        if not isinstance(item, dict):
            continue
        if item.get("data_id") == data_id:
            return item
    for item in extract_result:
        if not isinstance(item, dict):
            continue
        if str(item.get("file_name") or "") == normalized_name:
            return item
    return extract_result[0] if extract_result and isinstance(extract_result[0], dict) else None


def _extract_markdown_from_zip(zip_bytes: bytes) -> bytes:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        names = archive.namelist()
        preferred = next((name for name in names if name.endswith("full.md")), None)
        fallback = next((name for name in names if name.endswith(".md")), None)
        member = preferred or fallback
        if not member:
            raise NonRetryableError("MinerU result zip did not include full.md")
        return archive.read(member)


async def _convert_via_local_fallback(
    file_bytes: bytes,
    file_name: str,
    content_type: str | None,
    ext: str,
) -> NormalizedDocument:
    if ext == ".pdf":
        parsed = await parse_pdf(file_bytes, file_name, content_type or "application/pdf")
        markdown_bytes = _render_parsed_document_as_markdown(parsed)
    elif ext == ".docx":
        parsed = await parse_docx(
            file_bytes,
            file_name,
            content_type or "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        markdown_bytes = _render_parsed_document_as_markdown(parsed)
    elif ext in {".html", ".htm"}:
        # Pure-Python HTML→Markdown fallback (no external dependency). Adequate for Phase B
        # scope where MinerU is the primary path; this fallback only fires when MinerU is
        # unreachable. Addresses Phase B review MEDIUM #2 ("HTML 格式缺少本地 fallback").
        markdown_bytes = _render_html_as_markdown(file_bytes, file_name)
    else:  # pragma: no cover - guarded by caller
        raise NonRetryableError(f"No local fallback for extension {ext}")

    return NormalizedDocument(
        markdown_bytes=markdown_bytes,
        original_format=ext.lstrip("."),
        normalizer="mineru_fallback_local",
        cache_hit=False,
        normalized_at=_now_iso(),
    )


def _render_parsed_document_as_markdown(parsed: ParsedDocument) -> bytes:
    lines: list[str] = []
    has_heading = any(block.block_type == "heading" for block in parsed.blocks)
    if not has_heading and parsed.title:
        lines.append(f"# {parsed.title}")
        lines.append("")

    for block in parsed.blocks:
        if block.block_type == "heading":
            level = block.heading_level or 1
            lines.append(f"{'#' * max(1, level)} {block.text.strip()}")
        elif block.block_type == "code":
            lines.append("```")
            lines.append(block.text.rstrip())
            lines.append("```")
        else:
            lines.append(block.text.rstrip())
        lines.append("")
    return "\n".join(lines).strip().encode("utf-8")


# ---------------------------------------------------------------------------
# Minimal HTML→Markdown fallback (used only when MinerU is unreachable for HTML).
# ---------------------------------------------------------------------------

_HTML_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_HTML_TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_HTML_HEADING_RE = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
_HTML_PARAGRAPH_RE = re.compile(r"<(p|li|blockquote)\b[^>]*>(.*?)</\1>", re.IGNORECASE | re.DOTALL)
_HTML_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_HTML_CODE_RE = re.compile(r"<(?:pre|code)\b[^>]*>(.*?)</(?:pre|code)>", re.IGNORECASE | re.DOTALL)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\n{3,}")


def _render_html_as_markdown(file_bytes: bytes, file_name: str) -> bytes:
    """Strip HTML to approximate Markdown. Intentionally minimal — the primary path is MinerU."""
    try:
        text = file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = file_bytes.decode("latin-1", errors="replace")

    title_match = _HTML_TITLE_RE.search(text)
    title = html.unescape(_HTML_TAG_RE.sub("", title_match.group(1)).strip()) if title_match else ""

    text = _HTML_SCRIPT_STYLE_RE.sub("", text)
    text = _HTML_COMMENT_RE.sub("", text)
    text = _HTML_BR_RE.sub("\n", text)

    def _heading_sub(match: re.Match[str]) -> str:
        level = int(match.group(1))
        inner = html.unescape(_HTML_TAG_RE.sub("", match.group(2)).strip())
        return f"\n\n{'#' * level} {inner}\n\n"

    def _paragraph_sub(match: re.Match[str]) -> str:
        inner = html.unescape(_HTML_TAG_RE.sub("", match.group(2)).strip())
        if not inner:
            return ""
        prefix = "> " if match.group(1).lower() == "blockquote" else ""
        return f"\n\n{prefix}{inner}\n\n"

    def _code_sub(match: re.Match[str]) -> str:
        inner = html.unescape(match.group(1))
        return f"\n\n```\n{inner.strip()}\n```\n\n"

    text = _HTML_HEADING_RE.sub(_heading_sub, text)
    text = _HTML_CODE_RE.sub(_code_sub, text)
    text = _HTML_PARAGRAPH_RE.sub(_paragraph_sub, text)
    text = _HTML_TAG_RE.sub("", text)
    text = html.unescape(text)
    text = _WHITESPACE_RE.sub("\n\n", text).strip()

    if not text:
        fallback_title = title or Path(file_name).stem.replace("-", " ").replace("_", " ")
        text = f"# {fallback_title}\n\n(HTML document was empty after stripping tags)"
    elif title and not text.lstrip().startswith("#"):
        text = f"# {title}\n\n{text}"

    # Ensure there's always a sensible document title before downstream parsing.
    return text.encode("utf-8")
