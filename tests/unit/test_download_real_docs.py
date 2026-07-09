import json
import subprocess
from pathlib import Path

import pytest

from scripts import download_real_docs as download_module


def test_parse_source_selection_supports_all_and_subsets() -> None:
    all_sources = download_module.parse_source_selection("all")
    subset = download_module.parse_source_selection("affine,mineru")
    openclaw = download_module.parse_source_selection("openclaw")[0]

    assert [source["name"] for source in all_sources] == ["openclaw", "affine", "mineru"]
    assert [source["name"] for source in subset] == ["affine", "mineru"]
    assert openclaw["repo_url"] == "https://github.com/openclaw/openclaw.git"
    assert openclaw["license"] == "MIT"


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


def test_download_source_skip_reuses_existing_materialized_copy(tmp_path, monkeypatch) -> None:
    manifest_path = tmp_path / "manifest.json"
    auto_root = tmp_path / "auto"
    destination = auto_root / "mineru"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "README.md").write_text("# MinerU\n", encoding="utf-8")

    monkeypatch.setattr(download_module, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(download_module, "AUTO_ROOT", auto_root)
    monkeypatch.setattr(download_module, "REPO_TMP_ROOT", tmp_path / "download")

    manifest = {
        "generated_at": None,
        "schema_version": "v2",
        "auto_sources": {
            "mineru": {
                "repo_url": "https://github.com/opendatalab/MinerU.git",
                "branch": "master",
                "commit_sha": "def456",
                "retrieved_at": "2026-05-15T00:00:00Z",
                "file_count": 1,
                "total_bytes": 9,
                "license": "Apache-2.0-with-additional-terms",
                "license_verified": True,
                "sparse_paths": ["docs/", "README*.md"],
                "workspace_slug": "project_mineru",
                "materialized": True,
            }
        },
        "manual_curation": {},
        "errors": [
            {
                "source": "mineru",
                "type": "download_failed",
                "detail": "old transient failure",
                "timestamp": "2026-05-15T00:00:01Z",
            }
        ],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def fake_run(command: list[str], cwd=None, check=True, capture_output=True, text=True):  # noqa: ANN001
        if command[:2] == ["git", "ls-remote"]:
            return subprocess.CompletedProcess(command, 0, stdout="def456\trefs/heads/master\n", stderr="")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(download_module.subprocess, "run", fake_run)

    source = download_module.parse_source_selection("mineru")[0]
    result = download_module.download_source(source, force=False, dry_run=False)
    refreshed_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert result["status"] == "skipped"
    assert result["materialized_path"] == destination.as_posix()
    assert result["file_count"] == 1
    assert not (tmp_path / "download" / "mineru").exists()
    assert refreshed_manifest["errors"] == []


def test_download_source_clears_stale_repo_url_missing_error(tmp_path, monkeypatch) -> None:
    manifest_path = tmp_path / "manifest.json"
    auto_root = tmp_path / "auto"
    monkeypatch.setattr(download_module, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(download_module, "AUTO_ROOT", auto_root)
    monkeypatch.setattr(download_module, "REPO_TMP_ROOT", tmp_path / "download")

    manifest = {
        "generated_at": None,
        "schema_version": "v2",
        "auto_sources": {
            "openclaw": {
                "repo_url": "https://github.com/openclaw/openclaw.git",
                "branch": "main",
                "commit_sha": "abc123",
                "retrieved_at": "2026-05-15T00:00:00Z",
                "file_count": 0,
                "total_bytes": 0,
                "license": "MIT",
                "license_verified": None,
                "sparse_paths": ["docs/", "README.md", "README_*.md"],
                "workspace_slug": "project_openclaw",
                "materialized": False,
            }
        },
        "manual_curation": {},
        "errors": [
            {
                "source": "openclaw",
                "type": "repo_url_missing",
                "detail": "repo_url is empty; user must confirm the final repository URL.",
                "timestamp": "2026-05-13T04:27:10.166562Z",
            }
        ],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def fake_run(command: list[str], cwd=None, check=True, capture_output=True, text=True):  # noqa: ANN001
        if command[:2] == ["git", "ls-remote"]:
            return subprocess.CompletedProcess(command, 0, stdout="abc123\trefs/heads/main\n", stderr="")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(download_module.subprocess, "run", fake_run)

    source = download_module.parse_source_selection("openclaw")[0]
    result = download_module.download_source(source, force=False, dry_run=True)
    refreshed_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert result["status"] == "skipped"
    assert refreshed_manifest["errors"] == []


def test_collect_files_limits_root_matches_to_declared_readmes(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    docs_dir = repo_root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (repo_root / "README.md").write_text("# Readme\n", encoding="utf-8")
    (repo_root / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
    (repo_root / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    (docs_dir / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (docs_dir / "guide.txt").write_text("ignore me\n", encoding="utf-8")

    source = download_module.parse_source_selection("openclaw")[0]
    files = download_module._collect_files(repo_root, source)
    relative_paths = [path.relative_to(repo_root).as_posix() for path in files]

    assert relative_paths == ["README.md", "docs/guide.md"]


def test_materialize_files_falls_back_to_copytree_when_replace_is_blocked(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    source_file = repo_root / "README.md"
    source_file.write_text("# Readme\n", encoding="utf-8")
    destination = tmp_path / "output"

    original_replace = Path.replace

    def fake_replace(self: Path, target: Path | str) -> Path:  # noqa: ANN001
        if self.name == ".output.staging":
            raise PermissionError("rename blocked")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fake_replace)

    file_count, total_bytes = download_module._materialize_files([source_file], repo_root, destination)

    assert file_count == 1
    assert total_bytes == source_file.stat().st_size
    assert (destination / "README.md").read_text(encoding="utf-8") == "# Readme\n"
    assert not (tmp_path / ".output.staging").exists()
