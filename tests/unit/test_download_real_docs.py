from __future__ import annotations

import json
import subprocess

import pytest

from scripts import download_real_docs as download_module


def test_parse_source_selection_supports_all_and_subsets() -> None:
    all_sources = download_module.parse_source_selection("all")
    subset = download_module.parse_source_selection("affine,mineru")

    assert [source["name"] for source in all_sources] == ["openclaw", "affine", "mineru"]
    assert [source["name"] for source in subset] == ["affine", "mineru"]


def test_download_source_dry_run_skips_when_commit_is_unchanged(tmp_path: pytest.TempPathFactory, monkeypatch) -> None:
    manifest_path = tmp_path / "manifest.json"
    auto_root = tmp_path / "auto"
    monkeypatch.setattr(download_module, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(download_module, "AUTO_ROOT", auto_root)
    monkeypatch.setattr(download_module, "REPO_TMP_ROOT", tmp_path / "download")

    calls: list[list[str]] = []

    def fake_run(command: list[str], cwd=None, check=True, capture_output=True, text=True):  # noqa: ANN001
        calls.append(command)
        if command[:2] == ["git", "ls-remote"]:
            return subprocess.CompletedProcess(command, 0, stdout="abc123\trefs/heads/canary\n", stderr="")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(download_module.subprocess, "run", fake_run)

    source = download_module.parse_source_selection("affine")[0]
    first = download_module.download_source(source, force=False, dry_run=True)
    second = download_module.download_source(source, force=False, dry_run=True)

    assert first["status"] == "dry-run"
    assert second["status"] == "skipped"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["auto_sources"]["affine"]["commit_sha"] == "abc123"
    assert manifest["auto_sources"]["affine"]["materialized"] is False
    assert not auto_root.exists()
    assert len(calls) == 2


def test_download_sources_isolates_single_source_failures(tmp_path, monkeypatch) -> None:
    manifest_path = tmp_path / "manifest.json"
    auto_root = tmp_path / "auto"
    monkeypatch.setattr(download_module, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(download_module, "AUTO_ROOT", auto_root)
    monkeypatch.setattr(download_module, "REPO_TMP_ROOT", tmp_path / "download")

    def fake_run(command: list[str], cwd=None, check=True, capture_output=True, text=True):  # noqa: ANN001
        if command[:2] != ["git", "ls-remote"]:
            raise AssertionError(f"Unexpected command: {command}")
        repo_url = command[2]
        if "AFFiNE" in repo_url:
            raise subprocess.CalledProcessError(1, command, stderr="network boom")
        return subprocess.CompletedProcess(command, 0, stdout="def456\trefs/heads/master\n", stderr="")

    monkeypatch.setattr(download_module.subprocess, "run", fake_run)

    sources = download_module.parse_source_selection("affine,mineru")
    results = download_module.download_sources(sources, force=False, dry_run=True)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert [result["status"] for result in results] == ["failed", "dry-run"]
    assert manifest["auto_sources"]["mineru"]["commit_sha"] == "def456"
    assert any(error["source"] == "affine" and error["type"] == "download_failed" for error in manifest["errors"])
