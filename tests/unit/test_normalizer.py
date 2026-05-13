from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from src.common.exceptions import NonRetryableError, RetryableError
from src.config.settings import settings
from src.document.normalizer import normalize_to_markdown
from src.document.parser import ParsedBlock, ParsedDocument


def _zip_bytes(markdown: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("full.md", markdown)
    return buffer.getvalue()


async def test_normalizer_passthrough_markdown(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "normalizer_cache_dir", str(tmp_path / "normalized"))

    result = await normalize_to_markdown(b"# Title\n\nBody", "guide.md", "text/markdown")

    assert result.markdown_bytes == b"# Title\n\nBody"
    assert result.original_format == "md"
    assert result.normalizer == "passthrough"
    assert result.cache_hit is False


async def test_normalizer_wraps_plain_text(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "normalizer_cache_dir", str(tmp_path / "normalized"))

    result = await normalize_to_markdown(b"hello\nworld", "notes.txt", "text/plain")

    assert result.original_format == "txt"
    assert result.normalizer == "wrap_plain_text"
    assert result.markdown_bytes.startswith(b"# notes")
    assert b"hello\nworld" in result.markdown_bytes


async def test_normalizer_mineru_success_writes_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "normalizer_cache_dir", str(tmp_path / "normalized"))
    monkeypatch.setattr(settings, "mineru_api_key", "test-key")
    monkeypatch.setattr(settings, "mineru_api_base_url", "https://mineru.example/api/v4")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/file-urls/batch"):
            assert request.headers["Authorization"] == "Bearer test-key"
            payload = json.loads(request.content.decode("utf-8"))
            assert payload["model_version"] == "vlm"
            assert payload["files"][0]["name"] == "manual.pdf"
            return httpx.Response(
                200,
                json={"code": 0, "msg": "ok", "data": {"batch_id": "batch-123", "file_urls": ["https://upload.example/file-1"]}},
            )
        if request.url == httpx.URL("https://upload.example/file-1"):
            assert "Authorization" not in request.headers
            assert request.content == b"%PDF-1.4 test"
            return httpx.Response(200, text="")
        if request.url.path.endswith("/extract-results/batch/batch-123"):
            assert request.headers["Authorization"] == "Bearer test-key"
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "msg": "ok",
                    "data": {
                        "extract_result": [
                            {
                                "file_name": "manual.pdf",
                                "state": "done",
                                "full_zip_url": "https://cdn.example/results/manual.zip",
                            }
                        ]
                    },
                },
            )
        if request.url == httpx.URL("https://cdn.example/results/manual.zip"):
            return httpx.Response(200, content=_zip_bytes("# MinerU\n\nok"))
        raise AssertionError(f"Unexpected request path: {request.url.path}")

    transport = httpx.MockTransport(handler)

    class MockAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("src.document.normalizer.mineru.httpx.AsyncClient", MockAsyncClient)

    result = await normalize_to_markdown(b"%PDF-1.4 test", "manual.pdf", "application/pdf")

    assert result.normalizer == "mineru"
    assert result.cache_hit is False
    assert result.markdown_bytes == b"# MinerU\n\nok"
    cache_root = Path(settings.normalizer_cache_dir)
    assert any(cache_root.rglob("*.md"))
    assert any(cache_root.rglob("*.json"))


async def test_normalizer_timeout_falls_back_to_local_parser(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "normalizer_cache_dir", str(tmp_path / "normalized"))
    monkeypatch.setattr(settings, "mineru_api_key", "test-key")
    monkeypatch.setattr(settings, "normalizer_enable_fallback", True)

    async def raise_timeout(*args, **kwargs):
        raise RetryableError("timeout", backoff_seconds=0)

    async def fake_parse_pdf(file_bytes, file_name, content_type):
        return ParsedDocument(
            title="Fallback PDF",
            file_name=file_name,
            content_type=content_type,
            parser_name="pymupdf",
            parser_version="1.0",
            byte_size=len(file_bytes),
            blocks=[ParsedBlock(text="Recovered content", block_type="paragraph", section_path="Fallback PDF")],
            metadata={"page_count": 1},
        )

    monkeypatch.setattr("src.document.normalizer.mineru._fetch_markdown_via_mineru", raise_timeout)
    monkeypatch.setattr("src.document.normalizer.mineru.parse_pdf", fake_parse_pdf)

    result = await normalize_to_markdown(b"%PDF-1.4 fallback", "fallback.pdf", "application/pdf")

    assert result.normalizer == "mineru_fallback_local"
    assert result.cache_hit is False
    assert b"# Fallback PDF" in result.markdown_bytes
    assert b"Recovered content" in result.markdown_bytes


async def test_normalizer_rejects_unsupported_extensions(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "normalizer_cache_dir", str(tmp_path / "normalized"))

    with pytest.raises(NonRetryableError, match="unsupported format"):
        await normalize_to_markdown(b"a,b,c", "sheet.csv", "text/csv")


async def test_normalizer_cache_hit_skips_remote_call(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "normalizer_cache_dir", str(tmp_path / "normalized"))
    monkeypatch.setattr(settings, "mineru_api_key", "test-key")
    monkeypatch.setattr(settings, "mineru_api_base_url", "https://mineru.example/api/v4")
    call_count = {"value": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["value"] += 1
        if request.url.path.endswith("/file-urls/batch"):
            return httpx.Response(
                200,
                json={"code": 0, "msg": "ok", "data": {"batch_id": "batch-cache", "file_urls": ["https://upload.example/cache"]}},
            )
        if request.url == httpx.URL("https://upload.example/cache"):
            return httpx.Response(200, text="")
        if request.url.path.endswith("/extract-results/batch/batch-cache"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "msg": "ok",
                    "data": {
                        "extract_result": [
                            {
                                "file_name": "cached.pdf",
                                "state": "done",
                                "full_zip_url": "https://cdn.example/results/cache.zip",
                            }
                        ]
                    },
                },
            )
        if request.url == httpx.URL("https://cdn.example/results/cache.zip"):
            return httpx.Response(200, content=_zip_bytes("# Cached\n\nbody"))
        raise AssertionError(f"Unexpected request path: {request.url.path}")

    transport = httpx.MockTransport(handler)

    class MockAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("src.document.normalizer.mineru.httpx.AsyncClient", MockAsyncClient)

    first = await normalize_to_markdown(b"%PDF-1.4 cached", "cached.pdf", "application/pdf")
    second = await normalize_to_markdown(b"%PDF-1.4 cached", "cached.pdf", "application/pdf")

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.markdown_bytes == first.markdown_bytes
    assert call_count["value"] == 4


async def test_html_uses_official_mineru_html_model_version(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "normalizer_cache_dir", str(tmp_path / "normalized"))
    monkeypatch.setattr(settings, "mineru_api_key", "test-key")
    monkeypatch.setattr(settings, "mineru_api_base_url", "https://mineru.example/api/v4")

    seen = {"model_version": None}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/file-urls/batch"):
            payload = json.loads(request.content.decode("utf-8"))
            seen["model_version"] = payload["model_version"]
            return httpx.Response(
                200,
                json={"code": 0, "msg": "ok", "data": {"batch_id": "batch-html", "file_urls": ["https://upload.example/html"]}},
            )
        if request.url == httpx.URL("https://upload.example/html"):
            return httpx.Response(200, text="")
        if request.url.path.endswith("/extract-results/batch/batch-html"):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "msg": "ok",
                    "data": {
                        "extract_result": [
                            {
                                "file_name": "page.html",
                                "state": "done",
                                "full_zip_url": "https://cdn.example/results/page.zip",
                            }
                        ]
                    },
                },
            )
        if request.url == httpx.URL("https://cdn.example/results/page.zip"):
            return httpx.Response(200, content=_zip_bytes("# HTML\n\nok"))
        raise AssertionError(f"Unexpected request path: {request.url.path}")

    transport = httpx.MockTransport(handler)

    class MockAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("src.document.normalizer.mineru.httpx.AsyncClient", MockAsyncClient)

    result = await normalize_to_markdown(b"<html><body>ok</body></html>", "page.html", "text/html")

    assert seen["model_version"] == "MinerU-HTML"
    assert result.markdown_bytes == b"# HTML\n\nok"



# ---------------------------------------------------------------------------
# Phase B review regression tests
# ---------------------------------------------------------------------------


async def test_html_falls_back_to_local_when_mineru_unreachable(tmp_path, monkeypatch) -> None:
    """MEDIUM #2: HTML format must have a local fallback when MinerU fails."""
    from src.document.normalizer import mineru as mineru_module

    monkeypatch.setattr(settings, "normalizer_cache_dir", str(tmp_path / "normalized"))
    monkeypatch.setattr(settings, "mineru_api_key", "test-key")
    monkeypatch.setattr(settings, "normalizer_enable_fallback", True)

    async def raise_timeout(*args, **kwargs):
        raise RetryableError("timeout", backoff_seconds=0)

    monkeypatch.setattr(mineru_module, "_fetch_markdown_via_mineru", raise_timeout)

    html_bytes = (
        b"<html><head><title>Guide</title></head><body>"
        b"<h1>Intro</h1><p>Hello <em>world</em>.</p>"
        b"<pre><code>print('hi')</code></pre>"
        b"</body></html>"
    )

    result = await normalize_to_markdown(html_bytes, "page.html", "text/html")

    assert result.normalizer == "mineru_fallback_local"
    md_text = result.markdown_bytes.decode("utf-8")
    assert "# Intro" in md_text
    assert "Hello world." in md_text
    assert "```" in md_text and "print('hi')" in md_text


async def test_html_fallback_disabled_raises_non_retryable(tmp_path, monkeypatch) -> None:
    """MEDIUM #2 edge case: when fallback is disabled, HTML should surface the error clearly."""
    from src.document.normalizer import mineru as mineru_module

    monkeypatch.setattr(settings, "normalizer_cache_dir", str(tmp_path / "normalized"))
    monkeypatch.setattr(settings, "mineru_api_key", "test-key")
    monkeypatch.setattr(settings, "normalizer_enable_fallback", False)

    async def raise_timeout(*args, **kwargs):
        raise RetryableError("timeout", backoff_seconds=0)

    monkeypatch.setattr(mineru_module, "_fetch_markdown_via_mineru", raise_timeout)

    with pytest.raises(RetryableError):
        await normalize_to_markdown(b"<html></html>", "page.html", "text/html")


async def test_mineru_call_counter_resets_per_day(tmp_path, monkeypatch) -> None:
    """MEDIUM #4: the counter must NOT accumulate across days for long-running workers."""
    from src.document.normalizer import mineru as mineru_module

    mineru_module._reset_call_count_for_testing()
    monkeypatch.setattr(settings, "mineru_daily_call_budget", 1)

    first = mineru_module._bump_call_count()
    second = mineru_module._bump_call_count()
    assert first == 1
    assert second == 2

    # Simulate a date rollover by stomping the internal date key.
    mineru_module._MINERU_CALL_STATE["date"] = "1999-01-01"
    after_rollover = mineru_module._bump_call_count()
    assert after_rollover == 1, "counter must reset when the date changes"


async def test_mineru_deadline_covers_post_and_polling(tmp_path, monkeypatch) -> None:
    """MEDIUM #3: the deadline must start BEFORE the POST so a slow upload + polling
    can't exceed the configured total timeout."""
    from src.document.normalizer import mineru as mineru_module

    monkeypatch.setattr(settings, "normalizer_cache_dir", str(tmp_path / "normalized"))
    monkeypatch.setattr(settings, "mineru_api_key", "test-key")
    monkeypatch.setattr(settings, "mineru_api_base_url", "https://mineru.example/api/v4")
    monkeypatch.setattr(settings, "normalizer_enable_fallback", False)
    monkeypatch.setattr(settings, "mineru_request_timeout", 1.0)
    monkeypatch.setattr(settings, "mineru_poll_interval", 0.01)

    # Simulate a POST that takes longer than the entire timeout budget, then
    # returns — the next deadline check should immediately fire.
    elapsed = {"value": 0.0}
    real_monotonic = mineru_module.time.monotonic

    def fake_monotonic():
        # Advance virtual clock by 1.5s on each call so POST "takes" > deadline.
        elapsed["value"] += 0.6
        return real_monotonic() + elapsed["value"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/file-urls/batch"):
            return httpx.Response(
                200,
                json={"code": 0, "msg": "ok", "data": {"batch_id": "batch-slow", "file_urls": ["https://upload.example/slow"]}},
            )
        if request.url == httpx.URL("https://upload.example/slow"):
            return httpx.Response(200, text="")
        return httpx.Response(200, json={"code": 0, "msg": "ok", "data": {"extract_result": [{"state": "running"}]}})

    transport = httpx.MockTransport(handler)

    class MockAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("src.document.normalizer.mineru.httpx.AsyncClient", MockAsyncClient)
    monkeypatch.setattr("src.document.normalizer.mineru.time.monotonic", fake_monotonic)

    with pytest.raises(RetryableError, match="MinerU"):
        await normalize_to_markdown(b"%PDF-1.4", "slow.pdf", "application/pdf")
