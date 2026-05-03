"""Redis client helper."""
from __future__ import annotations

from redis.asyncio import Redis

from src.config.settings import settings


def get_redis_client() -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=False)

