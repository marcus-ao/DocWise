"""CLI for submitting local documents to the DocWise ingestion pipeline."""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from minio import Minio

from src.config.redactor import redact_secrets
from src.config.settings import settings
from src.db.redis import get_redis_client
from src.db.session import async_session_factory
from src.document.ingestion import guess_content_type, ingest_document_by_id, submit_document_for_ingestion


async def _read_bytes(path: Path) -> bytes:
    return await asyncio.to_thread(path.read_bytes)


async def ingest_path(path: Path, workspace: str, enqueue: bool) -> dict[str, object]:
    minio_client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    redis = get_redis_client()
    try:
        async with async_session_factory() as session:
            file_bytes = await _read_bytes(path)
            result = await submit_document_for_ingestion(
                session=session,
                redis=redis,
                minio_client=minio_client,
                file_bytes=file_bytes,
                file_name=path.name,
                workspace_slug=workspace,
                content_type=guess_content_type(path.name),
                enqueue=enqueue,
            )
        print(
            f"{path}: document_id={result['document_id']} job_id={result['job_id']} status={result['status']}",
            flush=True,
        )
        status = str(result.get("status", ""))
        if not enqueue and status in {"queued", "pending", "error"}:
            ingest_result = await ingest_document_by_id(result["document_id"], result.get("job_id"))
            result["status"] = str(ingest_result.get("status", "ingested"))
            print(f"{path}: ingested status={result['status']}", flush=True)
        return result
    finally:
        await redis.aclose()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest local documents into DocWise.")
    parser.add_argument("--workspace", required=True, help="Workspace slug, e.g. public_tech")
    parser.add_argument("--dir", required=True, help="Directory containing documents")
    parser.add_argument("--enqueue", action="store_true", help="Only enqueue arq jobs; default ingests synchronously")
    args = parser.parse_args()

    root = Path(args.dir)
    paths = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower().lstrip(".") in settings.allowed_file_type_list
    ]
    if not paths:
        raise SystemExit(f"No supported documents found under {root}")
    results = []
    for path in paths:
        results.append(await ingest_path(path, args.workspace, enqueue=args.enqueue))

    status_counts: dict[str, int] = {}
    for result in results:
        status = str(result.get("status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1
    summary = ", ".join(f"{status}={count}" for status, count in sorted(status_counts.items()))
    print("", flush=True)
    print(f"Ingestion command finished: files={len(results)} {summary}", flush=True)
    if args.enqueue:
        print("Async enqueue mode: keep the arq worker running, then check the job IDs above for progress.", flush=True)
    else:
        print("Sync mode: local ingestion processing has returned. Start the next command from the fresh prompt.", flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        raise SystemExit("Ingestion interrupted") from None
    except Exception as error:
        raise SystemExit(f"Ingestion failed: {redact_secrets(str(error))}") from None

