"""FastAPI dependency aliases."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from minio import Minio
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import settings
from src.db.redis import get_redis_client
from src.db.session import get_session


async def get_db():
    async for session in get_session():
        yield session


async def get_redis() -> Redis:
    return get_redis_client()


def get_minio() -> Minio:
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


DbSession = Annotated[AsyncSession, Depends(get_db)]


async def require_admin_auth(authorization: str | None = Header(default=None)) -> None:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authorization header required")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or token != settings.admin_api_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")


AdminAuth = Annotated[None, Depends(require_admin_auth)]


async def optional_admin_auth(authorization: str | None = Header(default=None)) -> None:
    if not settings.auth_enabled:
        return None
    await require_admin_auth(authorization)
