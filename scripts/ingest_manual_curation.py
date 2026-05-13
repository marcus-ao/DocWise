"""Ingest manually curated mixed-format documents into DocWise."""
from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml
from minio import Minio

from scripts.manifest_utils import (
    MANIFEST_PATH,
    MANUAL_ROOT,
    append_manifest_error,
    now_iso,
    sha256_file,
    update_manifest,
)
from src.config.redactor import redact_secrets
from src.config.settings import settings
from src.db.redis import get_redis_client
from src.db.session import async_session_factory
from src.document.ingestion import submit_document_for_ingestion

SUPPORTED_EXTENSIONS = {f".{item}" for item in settings.allowed_file_type_list}
WORKSPACE_ROOT_CATEGORY = "workspace_root"
MANUAL_CATEGORY_DIRECTORIES = [
    "public_tech/fastapi",
    "public_tech/mysql",
    "public_tech/docker",
    "public_tech/k8s",
    "public_tech/redis",
    "public_tech/langgraph",
    "public_tech/minio",
    "public_tech/external_misc/blogs",
    "public_tech/external_misc/tutorials",
    "public_tech/external_misc/papers",
]
DEFAULT_LICENSES_TEMPLATE = """default:
  license: user_declared
  attestation: "用户声明来自公开开放资源；如有争议以上游许可为准"

entries:
  public_tech/fastapi/:
    license: MIT
    source_pattern: "https://fastapi.tiangolo.com/*"
  public_tech/mysql/:
    license: GPL-2.0-with-FOSS-exception
    source_pattern: "https://dev.mysql.com/doc/*"
  public_tech/docker/:
    license: Apache-2.0
    source_pattern: "https://docs.docker.com/*"
  public_tech/k8s/:
    license: CC-BY-4.0
    source_pattern: "https://kubernetes.io/docs/*"
  public_tech/redis/:
    license: BSD-3-Clause
    source_pattern: "https://redis.io/docs/*"
  public_tech/langgraph/:
    license: MIT
    source_pattern: "https://langchain-ai.github.io/langgraph/*"
  public_tech/minio/:
    license: AGPL-3.0
    source_pattern: "https://min.io/docs/*"
  public_tech/external_misc/papers/:
    license: arxiv_nonexclusive
    notes: "每篇 paper 单独在 frontmatter 记录 arxiv_id"
"""


def ensure_manual_curation_layout(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for relative_dir in MANUAL_CATEGORY_DIRECTORIES:
        (root / relative_dir).mkdir(parents=True, exist_ok=True)
    licenses_path = root / "LICENSES.yaml"
    if not licenses_path.exists():
        licenses_path.write_text(DEFAULT_LICENSES_TEMPLATE, encoding="utf-8")
    return licenses_path


def load_licenses(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Required license manifest not found: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError("LICENSES.yaml must define a mapping at the top level")
    entries = loaded.get("entries") or {}
    if not isinstance(entries, dict):
        raise ValueError("LICENSES.yaml entries must be a mapping")
    loaded["entries"] = entries
    return loaded


def category_from_rel_path(rel_path: Path) -> str | None:
    if len(rel_path.parts) < 2:
        return None
    parent = rel_path.parent
    if len(parent.parts) < 2:
        return WORKSPACE_ROOT_CATEGORY
    return Path(*parent.parts[1:]).as_posix()


def walk_manual_files(root: Path, *, category: str | None = None) -> list[Path]:
    discovered: list[Path] = []
    category_filter = category.strip().lower() if category else None
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.name == "LICENSES.yaml":
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        rel_path = path.relative_to(root)
        current_category = (category_from_rel_path(rel_path) or "").lower()
        if category_filter and current_category != category_filter:
            continue
        discovered.append(path)
    discovered.sort(key=lambda item: item.relative_to(root).as_posix())
    return discovered


def resolve_license_entry(licenses: dict[str, Any], rel_path: Path) -> dict[str, Any] | None:
    entries = licenses.get("entries", {})
    rel_posix = rel_path.as_posix()
    best_key = ""
    best_entry: dict[str, Any] | None = None
    for key, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        normalized_key = str(key).strip().strip("/")
        if not normalized_key:
            continue
        if rel_posix == normalized_key or rel_posix.startswith(f"{normalized_key}/"):
            if len(normalized_key) > len(best_key):
                best_key = normalized_key
                best_entry = entry
    return best_entry


def build_manual_summary(files: list[Path], root: Path, licenses_path: Path) -> dict[str, Any]:
    categories: dict[str, dict[str, Any]] = {}
    format_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    file_counts: dict[str, int] = defaultdict(int)
    for file_path in files:
        rel_path = file_path.relative_to(root)
        category = category_from_rel_path(rel_path)
        if not category:
            continue
        file_counts[category] += 1
        format_counts[category][file_path.suffix.lstrip(".").lower()] += 1
    for category, count in sorted(file_counts.items()):
        categories[category] = {
            "file_count": count,
            "formats": dict(sorted(format_counts[category].items())),
        }
    return {
        "batch_id": now_iso()[:10],
        "licenses_yaml_hash": sha256_file(licenses_path),
        "categories": categories,
    }


async def ingest_manual_curation(
    *,
    category: str | None = None,
    dry_run: bool = False,
    skip_license_check: bool = False,
    enqueue: bool = False,
) -> dict[str, Any]:
    licenses_path = ensure_manual_curation_layout(MANUAL_ROOT)
    licenses = load_licenses(licenses_path)
    files = walk_manual_files(MANUAL_ROOT, category=category)
    summary = build_manual_summary(files, MANUAL_ROOT, licenses_path)
    results: dict[str, Any] = {"ingested": 0, "skipped": 0, "failed": 0, "errors": []}

    minio_client = None
    redis = None
    try:
        if not dry_run:
            minio_client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
            )
            redis = get_redis_client()

        for file_path in files:
            rel_path = file_path.relative_to(MANUAL_ROOT)
            workspace_slug = rel_path.parts[0]
            current_category = category_from_rel_path(rel_path)
            if workspace_slug.startswith("project_"):
                results["skipped"] += 1
                results["errors"].append({"path": rel_path.as_posix(), "reason": "project_workspace_not_supported"})
                append_manifest_error(
                    {
                        "path": rel_path.as_posix(),
                        "type": "project_workspace_not_supported",
                        "detail": "Manual curation only supports non-project workspaces.",
                        "timestamp": now_iso(),
                    },
                    MANIFEST_PATH,
                )
                continue

            license_entry = resolve_license_entry(licenses, rel_path)
            if license_entry is None and not skip_license_check:
                results["skipped"] += 1
                results["errors"].append({"path": rel_path.as_posix(), "reason": "license_not_declared"})
                append_manifest_error(
                    {
                        "path": rel_path.as_posix(),
                        "type": "license_not_declared",
                        "detail": "No matching LICENSES.yaml entry was found for this file.",
                        "timestamp": now_iso(),
                    },
                    MANIFEST_PATH,
                )
                continue

            provenance = {
                "source": "manual_curation",
                "source_category": current_category,
                "manual_collection_batch": summary["batch_id"],
                "original_format": file_path.suffix.lstrip(".").lower(),
                "original_path": rel_path.as_posix(),
                "license": license_entry.get("license") if license_entry else "unknown",
                "license_source": "LICENSES.yaml" if license_entry else "default",
            }

            if dry_run:
                results["ingested"] += 1
                continue

            try:
                assert redis is not None
                assert minio_client is not None
                async with async_session_factory() as session:
                    await submit_document_for_ingestion(
                        session=session,
                        redis=redis,
                        minio_client=minio_client,
                        file_bytes=await asyncio.to_thread(file_path.read_bytes),
                        file_name=file_path.name,
                        workspace_slug=workspace_slug,
                        content_type=None,
                        provenance=provenance,
                        enqueue=enqueue,
                    )
                results["ingested"] += 1
            except Exception as error:  # noqa: BLE001 - continue with sibling files.
                results["failed"] += 1
                detail = redact_secrets(str(error))
                results["errors"].append({"path": rel_path.as_posix(), "reason": detail})
                append_manifest_error(
                    {
                        "path": rel_path.as_posix(),
                        "type": "manual_ingest_failed",
                        "detail": detail,
                        "timestamp": now_iso(),
                    },
                    MANIFEST_PATH,
                )

        update_manifest("manual_curation", summary, MANIFEST_PATH)
        return results
    finally:
        if redis is not None:
            await redis.aclose()


async def main_async() -> None:
    parser = argparse.ArgumentParser(description="Ingest manually curated Phase B documents.")
    parser.add_argument("--dry-run", action="store_true", help="Inspect files and provenance without inserting documents.")
    parser.add_argument("--category", help="Optional category filter such as fastapi or external_misc/papers")
    parser.add_argument("--skip-license-check", action="store_true", help="Allow files without a LICENSES.yaml match.")
    parser.add_argument("--enqueue", action="store_true", help="Only enqueue ingestion jobs instead of running synchronously.")
    args = parser.parse_args()

    results = await ingest_manual_curation(
        category=args.category,
        dry_run=args.dry_run,
        skip_license_check=args.skip_license_check,
        enqueue=args.enqueue,
    )
    print(
        "Manual curation finished: "
        f"ingested={results['ingested']} skipped={results['skipped']} failed={results['failed']}",
        flush=True,
    )
    if results["errors"]:
        print(f"Errors recorded: {len(results['errors'])}", flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        raise SystemExit("Manual curation interrupted") from None
    except Exception as error:
        raise SystemExit(f"Manual curation failed: {redact_secrets(str(error))}") from None
