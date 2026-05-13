"""Helpers for the local raw-data manifest used by Phase B ingestion scripts."""
from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if os.name == "nt":
    import msvcrt
else:
    import fcntl

SCHEMA_VERSION = "v2"
REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = REPO_ROOT / "data" / "raw"
AUTO_ROOT = RAW_ROOT / "auto"
MANUAL_ROOT = RAW_ROOT / "manual"
MANIFEST_PATH = RAW_ROOT / "manifest.json"


def now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def default_manifest() -> dict[str, Any]:
    return {
        "generated_at": None,
        "schema_version": SCHEMA_VERSION,
        "auto_sources": {},
        "manual_curation": {},
        "errors": [],
    }


def _normalize_manifest(data: dict[str, Any] | None) -> dict[str, Any]:
    manifest = default_manifest()
    if isinstance(data, dict):
        manifest.update(data)
    if not isinstance(manifest.get("auto_sources"), dict):
        manifest["auto_sources"] = {}
    if not isinstance(manifest.get("manual_curation"), dict):
        manifest["manual_curation"] = {}
    if not isinstance(manifest.get("errors"), list):
        manifest["errors"] = []
    manifest["schema_version"] = SCHEMA_VERSION
    return manifest


def _read_manifest_unlocked(path: Path) -> dict[str, Any]:
    if not path.exists():
        return default_manifest()
    data = json.loads(path.read_text(encoding="utf-8"))
    return _normalize_manifest(data if isinstance(data, dict) else None)


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    return _read_manifest_unlocked(path)


@contextmanager
def _manifest_lock(path: Path):
    lock_path = path.with_name(f"{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "r+b" if lock_path.exists() else "w+b"
    with lock_path.open(mode) as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"0")
            handle.flush()
        if os.name == "nt":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def write_manifest(manifest: dict[str, Any], path: Path = MANIFEST_PATH) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = _normalize_manifest(manifest)
    manifest["generated_at"] = now_iso()
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp_path.replace(path)
    return manifest


def mutate_manifest(mutator: Callable[[dict[str, Any]], None], path: Path = MANIFEST_PATH) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _manifest_lock(path):
        manifest = _read_manifest_unlocked(path)
        mutator(manifest)
        return write_manifest(manifest, path)


def update_manifest(section: str, data: dict[str, Any], path: Path = MANIFEST_PATH) -> dict[str, Any]:
    def _mutate(manifest: dict[str, Any]) -> None:
        manifest[section] = data

    return mutate_manifest(_mutate, path)


def update_manifest_entry(section: str, key: str, value: dict[str, Any], path: Path = MANIFEST_PATH) -> dict[str, Any]:
    def _mutate(manifest: dict[str, Any]) -> None:
        current = manifest.get(section, {})
        if not isinstance(current, dict):
            current = {}
        current[key] = value
        manifest[section] = current

    return mutate_manifest(_mutate, path)


def append_manifest_error(error: dict[str, Any], path: Path = MANIFEST_PATH) -> dict[str, Any]:
    def _mutate(manifest: dict[str, Any]) -> None:
        errors = manifest.setdefault("errors", [])
        if not isinstance(errors, list):
            errors = manifest["errors"] = []
        errors.append(error)

    return mutate_manifest(_mutate, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"
