"""Qwen/DashScope embedding client with Redis cache."""
from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

import structlog
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, RateLimitError

from src.common.exceptions import NonRetryableError, RetryableError
from src.config.redactor import redact_secrets
from src.config.settings import settings
from src.db.redis import get_redis_client
from src.llm.model_router import get_provider_config

logger = structlog.get_logger(__name__)

EMBEDDING_CACHE_TTL = 86400
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 10.0
MAX_EMBEDDING_BATCH_SIZE = 10


def get_embedding_dim() -> int:
    return settings.embedding_dim


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _query_cache_key(text: str) -> str:
    return f"cache:query_embedding:{_hash_text(text)}"


def _content_cache_key(text: str) -> str:
    return f"cache:embedding:{settings.embedding_model}:{_hash_text(text)}"


def _embedding_client() -> tuple[AsyncOpenAI, str]:
    config = get_provider_config("embedding")
    return AsyncOpenAI(base_url=config.base_url, api_key=config.api_key), config.model


def _map_embedding_error(error: Exception) -> Exception:
    if isinstance(error, (RetryableError, NonRetryableError)):
        return error
    if isinstance(error, (APITimeoutError, APIConnectionError)):
        return RetryableError(redact_secrets(str(error)), backoff_seconds=2.0)
    if isinstance(error, RateLimitError):
        return RetryableError(redact_secrets(str(error)), backoff_seconds=5.0)
    if isinstance(error, APIStatusError):
        if error.status_code == 429:
            return RetryableError(redact_secrets(str(error)), backoff_seconds=5.0)
        return NonRetryableError(redact_secrets(str(error)))
    return NonRetryableError(redact_secrets(str(error)))


def _validate_embedding(vector: list[float]) -> list[float]:
    if len(vector) != get_embedding_dim():
        raise NonRetryableError("Embedding dimension mismatch")
    return [float(value) for value in vector]


async def _embed_inputs(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    client, model = _embedding_client()
    response: Any | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = await client.embeddings.create(
                model=model,
                input=texts,
                dimensions=get_embedding_dim(),
            )
            break
        except Exception as error:  # noqa: BLE001 - mapped into project contract exceptions.
            mapped_error = _map_embedding_error(error)
            if not isinstance(mapped_error, RetryableError) or attempt == MAX_RETRIES:
                raise mapped_error from error
            base_backoff = getattr(mapped_error, "backoff_seconds", BASE_BACKOFF_SECONDS)
            backoff_seconds = min(MAX_BACKOFF_SECONDS, base_backoff * (2**attempt))
            await asyncio.sleep(backoff_seconds)

    if response is None:
        raise NonRetryableError("Embedding request failed without response")
    data = sorted(response.data, key=lambda item: item.index)
    vectors = [_validate_embedding(list(item.embedding)) for item in data]
    if len(vectors) != len(texts):
        raise NonRetryableError("Embedding response count mismatch")
    return vectors


async def _redis_get_json(key: str) -> Any | None:
    client = get_redis_client()
    try:
        value = await client.get(key)
    except Exception as error:  # noqa: BLE001 - Redis cache failure must not block embedding.
        logger.warning("embedding_cache_read_failed", error=redact_secrets(str(error)))
        return None
    finally:
        await client.aclose()
    return json.loads(value) if value else None


async def _redis_set_json(key: str, value: Any, ttl: int) -> None:
    client = get_redis_client()
    try:
        await client.set(key, json.dumps(value), ex=ttl)
    except Exception as error:  # noqa: BLE001 - Redis cache failure must not block embedding.
        logger.warning("embedding_cache_write_failed", error=redact_secrets(str(error)))
    finally:
        await client.aclose()


async def embed_query(text: str) -> list[float]:
    vectors = await _embed_inputs([text])
    return vectors[0]


async def embed_with_cache(text: str, ttl: int = 300) -> list[float]:
    key = _query_cache_key(text)
    cached = await _redis_get_json(key)
    if cached is not None:
        return _validate_embedding(cached)
    vector = await embed_query(text)
    await _redis_set_json(key, vector, ttl)
    return vector


async def embed_batch(texts: list[str], batch_size: int = MAX_EMBEDDING_BATCH_SIZE) -> list[list[float]]:
    results: list[list[float] | None] = [None] * len(texts)
    effective_batch_size = max(1, min(batch_size, MAX_EMBEDDING_BATCH_SIZE))
    for start in range(0, len(texts), effective_batch_size):
        batch = texts[start : start + effective_batch_size]
        misses: list[tuple[int, str]] = []
        for offset, text in enumerate(batch):
            index = start + offset
            cached = await _redis_get_json(_content_cache_key(text))
            if cached is None:
                misses.append((index, text))
            else:
                results[index] = _validate_embedding(cached)

        if not misses:
            continue

        vectors = await _embed_inputs([text for _, text in misses])
        for (index, text), vector in zip(misses, vectors, strict=True):
            results[index] = vector
            await _redis_set_json(_content_cache_key(text), vector, EMBEDDING_CACHE_TTL)

    if any(vector is None for vector in results):
        raise NonRetryableError("Embedding batch result count mismatch")
    return [vector for vector in results if vector is not None]
