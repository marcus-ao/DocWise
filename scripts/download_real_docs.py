"""Download real project documentation with reproducible source-lock metadata."""
from __future__ import annotations

import argparse
import fnmatch
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from scripts.manifest_utils import (
    AUTO_ROOT,
    MANIFEST_PATH,
    REPO_ROOT,
    append_manifest_error,
    load_manifest,
    now_iso,
    update_manifest_entry,
)
from src.config.redactor import redact_secrets

REPO_TMP_ROOT = REPO_ROOT / ".tmp" / "download"
LICENSE_CANDIDATES = ("LICENSE", "LICENSE.md", "COPYING")
LICENSE_MATCH_PATTERNS: dict[str, tuple[str, ...]] = {
    "Apache-2.0": ("apache license", "version 2.0"),
    "Apache-2.0-with-additional-terms": ("apache license 2.0", "additional terms"),
    "MIT": ('"mit" license', "mit license", "permission is hereby granted, free of charge"),
    "AGPL-3.0": ("gnu affero general public license", "agpl"),
}

SOURCES: list[dict[str, Any]] = [
    {
        "name": "openclaw",
        "repo_url": "",  # 用户确认最终仓库地址
        "branch": "main",
        "sparse_paths": ["docs/", "README.md", "README_*.md"],
        "file_filter": r"\.md$",
        "exclude_patterns": [r"_partials/", r"archive/"],
        "max_files": 30,
        "workspace_slug": "project_openclaw",
        "license": "Apache-2.0",
    },
    {
        "name": "affine",
        "repo_url": "https://github.com/toeverything/AFFiNE.git",
        "branch": "canary",
        "sparse_paths": ["docs/"],
        "file_filter": r"\.md$",
        "exclude_patterns": [],
        "max_files": 40,
        "workspace_slug": "project_affine",
        "license": "MIT",
    },
    {
        "name": "mineru",
        "repo_url": "https://github.com/opendatalab/MinerU.git",
        "branch": "master",
        "sparse_paths": ["docs/", "README*.md"],
        "file_filter": r"\.md$",
        "exclude_patterns": [],
        "max_files": 20,
        "workspace_slug": "project_mineru",
        "license": "Apache-2.0-with-additional-terms",
        "license_match_patterns": ["apache license 2.0", "additional terms", "mineru open source license"],
    },
]


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, capture_output=True, text=True)


def _source_index() -> dict[str, dict[str, Any]]:
    return {str(source["name"]): source for source in SOURCES}


def parse_source_selection(raw_value: str) -> list[dict[str, Any]]:
    value = (raw_value or "all").strip().lower()
    index = _source_index()
    if value == "all":
        return [index[name] for name in index]
    names = [part.strip().lower() for part in value.split(",") if part.strip()]
    if not names:
        raise ValueError("No sources selected.")
    unknown = [name for name in names if name not in index]
    if unknown:
        raise ValueError(f"Unknown sources: {', '.join(unknown)}")
    return [index[name] for name in names]


def _ls_remote_head(repo_url: str, branch: str) -> str:
    result = _run(["git", "ls-remote", repo_url, f"refs/heads/{branch}"])
    line = next((item.strip() for item in result.stdout.splitlines() if item.strip()), "")
    if not line:
        raise RuntimeError(f"Could not resolve remote HEAD for {repo_url}@{branch}")
    return line.split()[0]


def _split_sparse_paths(entries: list[str]) -> tuple[list[str], list[str]]:
    directories: list[str] = []
    root_globs: list[str] = []
    for entry in entries:
        stripped = entry.strip("/")
        if not stripped:
            continue
        if any(char in stripped for char in "*?[]") or "." in Path(stripped).name:
            root_globs.append(Path(stripped).name)
        else:
            directories.append(stripped)
    return directories, root_globs


def _configure_checkout(tmp_dir: Path, directories: list[str]) -> None:
    _run(["git", "-C", str(tmp_dir), "sparse-checkout", "init", "--cone"])
    if directories:
        _run(["git", "-C", str(tmp_dir), "sparse-checkout", "set", *directories])


def _checkout_root_matches(tmp_dir: Path, patterns: list[str]) -> None:
    if not patterns:
        return
    result = _run(["git", "-C", str(tmp_dir), "ls-tree", "--name-only", "HEAD"])
    root_names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    matches = sorted({name for name in root_names if any(fnmatch.fnmatch(name, pattern) for pattern in patterns)})
    if matches:
        _run(["git", "-C", str(tmp_dir), "checkout", "HEAD", "--", *matches])


def _ensure_checkout(source: dict[str, Any], tmp_dir: Path) -> str:
    branch = str(source["branch"])
    repo_url = str(source["repo_url"])
    directories, root_globs = _split_sparse_paths(list(source["sparse_paths"]))
    if tmp_dir.joinpath(".git").is_dir():
        _run(["git", "-C", str(tmp_dir), "fetch", "--depth=1", "origin", branch])
        _configure_checkout(tmp_dir, directories)
        _run(["git", "-C", str(tmp_dir), "checkout", "--detach", f"origin/{branch}"])
    else:
        tmp_dir.parent.mkdir(parents=True, exist_ok=True)
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        _run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                "--depth=1",
                "--branch",
                branch,
                repo_url,
                str(tmp_dir),
            ]
        )
        _configure_checkout(tmp_dir, directories)
        _run(["git", "-C", str(tmp_dir), "checkout", "--detach"])
    _checkout_root_matches(tmp_dir, root_globs)
    return _run(["git", "-C", str(tmp_dir), "rev-parse", "HEAD"]).stdout.strip()


def _license_matchers(source: dict[str, Any]) -> tuple[str, ...]:
    declared_license = str(source["license"])
    configured = tuple(str(item).lower() for item in source.get("license_match_patterns", []))
    if configured:
        return configured
    return LICENSE_MATCH_PATTERNS.get(declared_license, (declared_license.lower(),))


def _detect_repo_license(tmp_dir: Path, source: dict[str, Any]) -> tuple[str, bool]:
    declared_license = str(source["license"])
    matchers = _license_matchers(source)
    for candidate in LICENSE_CANDIDATES:
        path = tmp_dir / candidate
        if not path.exists():
            continue
        snippet = path.read_text(encoding="utf-8", errors="ignore")[:1000].lower()
        verified = any(matcher in snippet for matcher in matchers if matcher)
        return declared_license, verified
    return declared_license, False


def _collect_files(tmp_dir: Path, source: dict[str, Any]) -> list[Path]:
    include_re = re.compile(str(source["file_filter"]), re.IGNORECASE)
    exclude_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in source.get("exclude_patterns", [])]
    files: list[Path] = []
    for path in tmp_dir.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(tmp_dir).as_posix()
        if relative.startswith(".git/"):
            continue
        if not include_re.search(relative):
            continue
        if any(pattern.search(relative) for pattern in exclude_patterns):
            continue
        files.append(path)
    files.sort(key=lambda item: item.relative_to(tmp_dir).as_posix())
    return files[: int(source["max_files"])]


def _materialize_files(files: list[Path], tmp_dir: Path, destination: Path) -> tuple[int, int]:
    staging = destination.parent / f".{destination.name}.staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    total_bytes = 0
    for file_path in files:
        relative = file_path.relative_to(tmp_dir)
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, target)
        total_bytes += file_path.stat().st_size
    shutil.rmtree(destination, ignore_errors=True)
    if destination.exists():
        destination.unlink()
    staging.replace(destination)
    return len(files), total_bytes


def _source_entry(
    source: dict[str, Any],
    *,
    commit_sha: str,
    retrieved_at: str,
    materialized: bool,
    file_count: int,
    total_bytes: int,
    license_value: str,
    license_verified: bool | None,
) -> dict[str, Any]:
    return {
        "repo_url": source["repo_url"],
        "branch": source["branch"],
        "commit_sha": commit_sha,
        "retrieved_at": retrieved_at,
        "file_count": file_count,
        "total_bytes": total_bytes,
        "license": license_value,
        "license_verified": license_verified,
        "sparse_paths": list(source["sparse_paths"]),
        "workspace_slug": source["workspace_slug"],
        "materialized": materialized,
    }


def _update_auto_source(name: str, entry: dict[str, Any]) -> None:
    update_manifest_entry("auto_sources", name, entry, MANIFEST_PATH)


def download_source(source: dict[str, Any], *, force: bool, dry_run: bool) -> dict[str, Any]:
    name = str(source["name"])
    repo_url = str(source["repo_url"])
    manifest = load_manifest(MANIFEST_PATH)
    existing = manifest.get("auto_sources", {}).get(name, {}) if isinstance(manifest.get("auto_sources"), dict) else {}
    destination = AUTO_ROOT / name
    current_materialized = bool(existing.get("materialized")) and destination.exists()
    if not repo_url:
        append_manifest_error(
            {
                "source": name,
                "type": "repo_url_missing",
                "detail": "repo_url is empty; user must confirm the final repository URL.",
                "timestamp": now_iso(),
            },
            MANIFEST_PATH,
        )
        return {"source": name, "status": "skipped", "reason": "repo_url_missing"}

    remote_sha = _ls_remote_head(repo_url, str(source["branch"]))
    if dry_run and not force and remote_sha == existing.get("commit_sha"):
        print(f"{name}: skipped (commit_sha unchanged)", flush=True)
        return {"source": name, "status": "skipped", "commit_sha": remote_sha}
    if not dry_run and not force and remote_sha == existing.get("commit_sha") and current_materialized:
        print(f"{name}: skipped (commit_sha unchanged)", flush=True)
        return {"source": name, "status": "skipped", "commit_sha": remote_sha}

    if dry_run:
        entry = _source_entry(
            source,
            commit_sha=remote_sha,
            retrieved_at=now_iso(),
            materialized=current_materialized,
            file_count=int(existing.get("file_count", 0) or 0),
            total_bytes=int(existing.get("total_bytes", 0) or 0),
            license_value=str(source["license"]),
            license_verified=existing.get("license_verified") if existing else None,
        )
        _update_auto_source(name, entry)
        print(f"{name}: dry-run ready commit_sha={remote_sha}", flush=True)
        return {"source": name, "status": "dry-run", "commit_sha": remote_sha}

    tmp_dir = REPO_TMP_ROOT / name
    commit_sha = _ensure_checkout(source, tmp_dir)
    license_value, license_verified = _detect_repo_license(tmp_dir, source)
    if not license_verified:
        append_manifest_error(
            {
                "source": name,
                "type": "license_mismatch",
                "detail": f"Declared license {source['license']} did not match detected repository text.",
                "timestamp": now_iso(),
            },
            MANIFEST_PATH,
        )
    files = _collect_files(tmp_dir, source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    file_count, total_bytes = _materialize_files(files, tmp_dir, destination)
    entry = _source_entry(
        source,
        commit_sha=commit_sha,
        retrieved_at=now_iso(),
        materialized=True,
        file_count=file_count,
        total_bytes=total_bytes,
        license_value=license_value,
        license_verified=license_verified,
    )
    _update_auto_source(name, entry)
    print(f"{name}: downloaded files={file_count} commit_sha={commit_sha}", flush=True)
    return {"source": name, "status": "downloaded", "commit_sha": commit_sha, "file_count": file_count}


def download_sources(sources: list[dict[str, Any]], *, force: bool, dry_run: bool) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for source in sources:
        try:
            results.append(download_source(source, force=force, dry_run=dry_run))
        except Exception as error:  # noqa: BLE001 - source failures must not block siblings.
            name = str(source["name"])
            append_manifest_error(
                {
                    "source": name,
                    "type": "download_failed",
                    "detail": redact_secrets(str(error)),
                    "timestamp": now_iso(),
                },
                MANIFEST_PATH,
            )
            print(f"{name}: failed ({redact_secrets(str(error))})", flush=True)
            results.append({"source": name, "status": "failed", "error": redact_secrets(str(error))})
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Download reproducible real-world docs for Phase B.")
    parser.add_argument("--source", default="all", help="all or a comma-separated subset such as affine,mineru")
    parser.add_argument("--force", action="store_true", help="Ignore manifest SHA matches and refresh the source.")
    parser.add_argument("--dry-run", action="store_true", help="Only compare remote commit SHA and update source-lock.")
    parser.add_argument("--clean-tmp", action="store_true", help="Remove .tmp/download after the run.")
    args = parser.parse_args()

    sources = parse_source_selection(args.source)
    results = download_sources(sources, force=args.force, dry_run=args.dry_run)
    if args.clean_tmp:
        shutil.rmtree(REPO_TMP_ROOT, ignore_errors=True)

    counts: dict[str, int] = {}
    for result in results:
        status = str(result.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    summary = ", ".join(f"{status}={count}" for status, count in sorted(counts.items()))
    print(f"Download command finished: sources={len(results)} {summary}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit("Download interrupted") from None
    except Exception as error:
        raise SystemExit(f"Download failed: {redact_secrets(str(error))}") from None
