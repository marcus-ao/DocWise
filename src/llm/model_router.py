"""Model/provider routing for OpenAI-compatible LLM calls."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from src.config.settings import settings

ModelPurpose = Literal["fast", "pro", "embedding", "reranker"]


class ProviderConfig(BaseModel):
    provider: str
    base_url: str
    api_key: str
    model: str


def get_model_name(purpose: str) -> str:
    if purpose in (None, "", "fast"):
        return settings.llm_fast_model
    if purpose == "pro":
        return settings.llm_pro_model
    if purpose == "embedding":
        return settings.embedding_model
    if purpose in ("rerank", "reranker"):
        return settings.reranker_model
    raise ValueError(f"Unknown model purpose: {purpose}")


def get_provider_config(purpose: str | None = None, model: str | None = None) -> ProviderConfig:
    resolved_model = model or get_model_name(purpose or "fast")

    if purpose in {"embedding", "rerank", "reranker"} or resolved_model in {
        settings.embedding_model,
        settings.reranker_model,
    }:
        return ProviderConfig(
            provider="dashscope",
            base_url=settings.dashscope_base_url,
            api_key=settings.dashscope_api_key,
            model=resolved_model,
        )

    return ProviderConfig(
        provider="deepseek",
        base_url=settings.deepseek_base_url,
        api_key=settings.deepseek_api_key,
        model=resolved_model,
    )
