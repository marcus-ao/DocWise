from http import HTTPStatus
from types import SimpleNamespace

import pytest

from src.retrieval import reranker


def _chunk(chunk_id: str, rrf_score: float) -> dict:
    return {"chunk_id": chunk_id, "rrf_score": rrf_score, "content": f"content {chunk_id}"}


@pytest.mark.asyncio
async def test_dashscope_reranker_success_maps_results(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = [_chunk("a", 0.01), _chunk("b", 0.02), _chunk("c", 0.03)]
    response = SimpleNamespace(
        status_code=HTTPStatus.OK,
        output=SimpleNamespace(
            results=[
                SimpleNamespace(index=2, relevance_score=0.91),
                SimpleNamespace(index=0, relevance_score=0.72),
            ]
        ),
    )

    async def fake_call(**kwargs: object) -> object:
        assert kwargs["model"] == "qwen3-rerank"
        assert kwargs["top_n"] == 2
        return response

    monkeypatch.setattr(reranker.settings, "reranker_enabled", True)
    monkeypatch.setattr(
        reranker,
        "get_provider_config",
        lambda purpose: SimpleNamespace(model="qwen3-rerank", api_key="test-key"),
    )
    monkeypatch.setattr(reranker, "_call_dashscope_rerank", fake_call)

    result, fallback = await reranker.rerank("query", chunks, top_k=2)

    assert fallback is False
    assert [item["chunk_id"] for item in result] == ["c", "a"]
    assert result[0]["rerank_score"] == 0.91
    assert result[0]["final_rank"] == 1


@pytest.mark.asyncio
async def test_dashscope_reranker_non_ok_response_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks = [_chunk("a", 0.05), _chunk("b", 0.03)]
    response = SimpleNamespace(status_code=400, code="InvalidParameter", message="bad request")

    async def fake_call(**kwargs: object) -> object:
        return response

    monkeypatch.setattr(reranker.settings, "reranker_enabled", True)
    monkeypatch.setattr(
        reranker,
        "get_provider_config",
        lambda purpose: SimpleNamespace(model="qwen3-rerank", api_key="test-key"),
    )
    monkeypatch.setattr(reranker, "_call_dashscope_rerank", fake_call)

    result, fallback = await reranker.rerank("query", chunks, top_k=2)

    assert fallback is True
    assert [item["chunk_id"] for item in result] == ["a", "b"]
