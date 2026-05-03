"""Seed all local demo prerequisites that do not require model API calls."""
from __future__ import annotations

import asyncio

from minio import Minio

from scripts import download_docs, generate_mock_data
from scripts.seed_eval_cases import seed_eval_cases
from scripts.seed_workspaces import main as seed_workspaces_main
from src.common.minio import ensure_minio_bucket
from src.config.settings import settings


async def seed_minio_bucket() -> None:
    minio_client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    await ensure_minio_bucket(minio_client, settings.minio_bucket)
    print(f"MinIO bucket ready: {settings.minio_bucket}")


async def main() -> None:
    await seed_minio_bucket()
    await seed_workspaces_main()
    download_docs.main()
    generate_mock_data.main()
    inserted, updated = await seed_eval_cases()
    print(f"Seed demo complete: eval_cases inserted={inserted}, updated={updated}")


if __name__ == "__main__":
    asyncio.run(main())
