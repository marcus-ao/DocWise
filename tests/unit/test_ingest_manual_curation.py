from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import ingest_manual_curation as manual_module


def _write_manual_tree(root: Path) -> None:
    (root / "public_tech" / "fastapi").mkdir(parents=True, exist_ok=True)
    (root / "public_tech" / "external_misc" / "papers").mkdir(parents=True, exist_ok=True)
    (root / "public_tech" / "fastapi" / "tutorial-01.pdf").write_bytes(b"%PDF-1.4")
    (root / "public_tech" / "external_misc" / "papers" / "paper-01.md").write_text("# Paper", encoding="utf-8")


def _write_licenses(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "entries:",
                "  public_tech/fastapi/:",
                "    license: MIT",
                "  public_tech/external_misc/papers/:",
                "    license: arxiv_nonexclusive",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_ensure_manual_curation_layout_creates_template_and_directories(tmp_path) -> None:
    manual_root = tmp_path / "manual"

    licenses_path = manual_module.ensure_manual_curation_layout(manual_root)

    assert licenses_path.exists()
    assert (manual_root / "public_tech" / "fastapi").is_dir()
    assert (manual_root / "public_tech" / "external_misc" / "papers").is_dir()


def test_load_licenses_and_resolve_longest_prefix(tmp_path) -> None:
    manual_root = tmp_path / "manual"
    manual_root.mkdir(parents=True, exist_ok=True)
    licenses_path = manual_root / "LICENSES.yaml"
    _write_licenses(licenses_path)

    licenses = manual_module.load_licenses(licenses_path)
    entry = manual_module.resolve_license_entry(licenses, Path("public_tech/external_misc/papers/paper-01.md"))

    assert entry is not None
    assert entry["license"] == "arxiv_nonexclusive"


@pytest.mark.asyncio
async def test_ingest_manual_curation_uses_workspace_from_directory(tmp_path, monkeypatch) -> None:
    manual_root = tmp_path / "manual"
    manifest_path = tmp_path / "manifest.json"
    _write_manual_tree(manual_root)
    _write_licenses(manual_root / "LICENSES.yaml")

    captured: list[dict] = []

    class FakeRedis:
        async def aclose(self) -> None:
            return None

    class FakeSession:
        async def __aenter__(self):  # noqa: ANN204
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001, ANN204
            return False

    async def fake_submit_document_for_ingestion(**kwargs):  # noqa: ANN003
        assert "session" in kwargs
        assert "redis" in kwargs
        assert "minio_client" in kwargs
        assert "file_bytes" in kwargs
        assert "provenance" in kwargs
        captured.append(kwargs)
        return {"document_id": "doc-1", "status": "queued"}

    monkeypatch.setattr(manual_module, "MANUAL_ROOT", manual_root)
    monkeypatch.setattr(manual_module, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(manual_module, "Minio", lambda *args, **kwargs: object())
    monkeypatch.setattr(manual_module, "get_redis_client", lambda: FakeRedis())
    monkeypatch.setattr(manual_module, "async_session_factory", lambda: FakeSession())
    monkeypatch.setattr(manual_module, "submit_document_for_ingestion", fake_submit_document_for_ingestion)

    result = await manual_module.ingest_manual_curation(category="fastapi", dry_run=False)

    assert result["ingested"] == 1
    assert captured[0]["workspace_slug"] == "public_tech"
    assert captured[0]["provenance"]["source_category"] == "fastapi"


@pytest.mark.asyncio
async def test_ingest_manual_curation_assigns_workspace_root_category(tmp_path, monkeypatch) -> None:
    manual_root = tmp_path / "manual"
    manifest_path = tmp_path / "manifest.json"
    manual_module.ensure_manual_curation_layout(manual_root)
    (manual_root / "public_tech" / "overview.md").write_text("# Overview", encoding="utf-8")

    monkeypatch.setattr(manual_module, "MANUAL_ROOT", manual_root)
    monkeypatch.setattr(manual_module, "MANIFEST_PATH", manifest_path)

    result = await manual_module.ingest_manual_curation(dry_run=True, skip_license_check=True, category="workspace_root")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert result["ingested"] == 1
    assert manifest["manual_curation"]["categories"]["workspace_root"]["file_count"] == 1


@pytest.mark.asyncio
async def test_ingest_manual_curation_skips_missing_license_by_default(tmp_path, monkeypatch) -> None:
    manual_root = tmp_path / "manual"
    manifest_path = tmp_path / "manifest.json"
    (manual_root / "public_tech" / "docker").mkdir(parents=True, exist_ok=True)
    (manual_root / "public_tech" / "docker" / "guide.md").write_text("# Docker", encoding="utf-8")
    (manual_root / "LICENSES.yaml").write_text("entries: {}\n", encoding="utf-8")

    monkeypatch.setattr(manual_module, "MANUAL_ROOT", manual_root)
    monkeypatch.setattr(manual_module, "MANIFEST_PATH", manifest_path)

    result = await manual_module.ingest_manual_curation(dry_run=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert result["skipped"] == 1
    assert result["ingested"] == 0
    assert any(error["type"] == "license_not_declared" for error in manifest["errors"])


@pytest.mark.asyncio
async def test_ingest_manual_curation_dry_run_does_not_submit(tmp_path, monkeypatch) -> None:
    manual_root = tmp_path / "manual"
    manifest_path = tmp_path / "manifest.json"
    _write_manual_tree(manual_root)
    _write_licenses(manual_root / "LICENSES.yaml")

    called = False

    async def fake_submit_document_for_ingestion(**kwargs):  # noqa: ANN003
        nonlocal called
        called = True
        return {"document_id": "doc-1", "status": "queued"}

    monkeypatch.setattr(manual_module, "MANUAL_ROOT", manual_root)
    monkeypatch.setattr(manual_module, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(manual_module, "submit_document_for_ingestion", fake_submit_document_for_ingestion)

    result = await manual_module.ingest_manual_curation(category="external_misc/papers", dry_run=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert result["ingested"] == 1
    assert called is False
    assert "external_misc/papers" in manifest["manual_curation"]["categories"]
