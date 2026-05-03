"""FastAPI application factory."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from minio import Minio

from src.api.routers import admin, agent, chat, documents, eval
from src.config.settings import settings
from src.db.redis import get_redis_client
from src.db.session import engine

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix=settings.api_prefix)
app.include_router(agent.router, prefix=settings.api_prefix)
app.include_router(documents.router, prefix=settings.api_prefix)
app.include_router(eval.router, prefix=settings.api_prefix)
app.include_router(admin.router, prefix=settings.api_prefix)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    checks: dict[str, str] = {}
    try:
        async with engine.connect() as connection:
            await connection.exec_driver_sql("SELECT 1")
        checks["db"] = "ok"
    except Exception:
        checks["db"] = "unavailable"

    redis = get_redis_client()
    try:
        await redis.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unavailable"
    finally:
        await redis.aclose()

    try:
        Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        ).bucket_exists(settings.minio_bucket)
        checks["minio"] = "ok"
    except Exception:
        checks["minio"] = "unavailable"

    checks["status"] = "ready" if all(value == "ok" for value in checks.values()) else "degraded"
    return checks
