"""Qwen qwen3-rerank API with RRF-score fallback."""
from __future__ import annotations

import asyncio
from http import HTTPStatus
from typing import Any

import structlog
from dashscope import TextReRank

from src.agent.state import RERANK_TOP_K
from src.common.exceptions import NonRetryableError, RetryableError
from src.config.redactor import redact_secrets
from src.config.settings import settings
from src.llm.model_router import get_provider_config

logger = structlog.get_logger(__name__)


async def rerank(
    query: str,
    chunks: list[dict],
    top_k: int = RERANK_TOP_K,
) -> tuple[list[dict], bool]:
    """Rerank chunks using DashScope TextReRank.

    Returns (reranked_chunks, fallback_used). On API failure, falls back to
    RRF-score ordering without re-normalisation.
    """
    if not chunks:
        return [], False
    if not settings.reranker_enabled:
        logger.info("reranker_disabled")
        return _fallback(chunks, top_k)

    try:
        config = get_provider_config("reranker")
        if not config.api_key:
            logger.warning("reranker_skipped_missing_api_key")
            return _fallback(chunks, top_k)

        documents = [str(chunk.get("content") or "") for chunk in chunks]
        response = await _call_dashscope_rerank(
            model=config.model,
            query=query,
            documents=documents,
            top_n=min(top_k, len(chunks)),
            api_key=config.api_key,
        )

        if int(_get_value(response, "status_code", 0) or 0) != int(HTTPStatus.OK):
            logger.warning(
                "reranker_api_failed_response",
                code=_get_value(response, "code", ""),
                message=redact_secrets(str(_get_value(response, "message", ""))),
                request_id=_get_value(response, "request_id", ""),
            )
            return _fallback(chunks, top_k)

        ranked_indices = _extract_ranked_indices(response)
        if not ranked_indices:
            return _fallback(chunks, top_k)

        reranked: list[dict] = []
        for final_rank, item in enumerate(ranked_indices[:top_k], start=1):
            idx = int(_get_value(item, "index", _get_value(item, "document_index", 0)) or 0)
            score = float(_get_value(item, "relevance_score", _get_value(item, "score", 0.0)) or 0.0)
            if 0 <= idx < len(chunks):
                entry = {**chunks[idx]}
                entry["rerank_score"] = score
                entry["final_rank"] = final_rank
                reranked.append(entry)

        if not reranked:
            return _fallback(chunks, top_k)

        return reranked, False

    except (RetryableError, NonRetryableError):
        logger.warning("reranker_api_failed_contract_error", query=query[:80])
        return _fallback(chunks, top_k)
    except Exception:
        logger.warning("reranker_api_failed", query=query[:80], exc_info=True)
        return _fallback(chunks, top_k)


def _fallback(chunks: list[dict], top_k: int) -> tuple[list[dict], bool]:
    """Fallback: sort by rrf_score descending, take top_k. No re-normalisation."""
    sorted_chunks = sorted(chunks, key=lambda c: c.get("rrf_score", 0.0), reverse=True)
    result: list[dict] = []
    for final_rank, chunk in enumerate(sorted_chunks[:top_k], start=1):
        entry = {**chunk}
        entry["final_rank"] = final_rank
        result.append(entry)
    return result, True


async def _call_dashscope_rerank(
    model: str,
    query: str,
    documents: list[str],
    top_n: int,
    api_key: str,
) -> Any:
    return await asyncio.to_thread(
        TextReRank.call,
        model=model,
        query=query,
        documents=documents,
        return_documents=False,
        top_n=top_n,
        api_key=api_key,
    )


def _extract_ranked_indices(response: Any) -> list[Any]:
    output = _get_value(response, "output")
    results = _get_value(output, "results", [])
    return list(results or [])


def _get_value(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    if hasattr(obj, "get"):
        try:
            return obj.get(key, default)
        except TypeError:
            pass
    return getattr(obj, key, default)
