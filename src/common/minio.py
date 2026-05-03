"""Shared MinIO helpers."""
from __future__ import annotations

import asyncio

from minio import Minio
from minio.error import S3Error

_BUCKET_ALREADY_EXISTS_CODES = {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}


async def ensure_minio_bucket(minio_client: Minio, bucket: str) -> None:
    """Create the configured bucket when it is missing.

    The check is intentionally async-friendly because MinIO's Python client is
    synchronous. Concurrent first uploads may race on bucket creation, so the
    benign "already exists" responses are treated as success after a re-check.
    """
    if await asyncio.to_thread(minio_client.bucket_exists, bucket):
        return

    try:
        await asyncio.to_thread(minio_client.make_bucket, bucket)
    except S3Error as error:
        if error.code not in _BUCKET_ALREADY_EXISTS_CODES:
            raise
        if not await asyncio.to_thread(minio_client.bucket_exists, bucket):
            raise
