import hashlib
from types import SimpleNamespace

import pytest

import src.document.chunker as chunker_module
import src.document.embedder as embedder_module
import src.llm.client as llm_client
from src.document.chunker import chunk_document, detect_language, generate_chunk_uid
from src.document.embedder import embed_batch
from src.document.parser import ParsedBlock, ParsedDocument
from src.llm.model_router import get_model_name


def _parsed_document() -> ParsedDocument:
    return ParsedDocument(
        title="Airflow Troubleshooting",
        file_name="airflow.md",
        content_type="text/markdown",
        parser_name="test",
        parser_version="1.0",
        byte_size=512,
        blocks=[
            ParsedBlock(
                text="Airflow Troubleshooting",
                block_type="heading",
                heading_level=1,
                section_path="Airflow Troubleshooting",
            ),
            ParsedBlock(
                text="Scheduler Heartbeat",
                block_type="heading",
                heading_level=2,
                section_path="Airflow Troubleshooting > Scheduler Heartbeat",
                source_anchor="scheduler-heartbeat",
            ),
            ParsedBlock(
                text="Check the scheduler heartbeat and worker logs. " * 80,
                block_type="paragraph",
                section_path="Airflow Troubleshooting > Scheduler Heartbeat",
                source_anchor="scheduler-heartbeat",
            ),
            ParsedBlock(
                text="kubectl logs airflow-worker",
                block_type="code",
                section_path="Airflow Troubleshooting > Scheduler Heartbeat",
                contains_code=True,
            ),
        ],
    )


def test_generate_chunk_uid_is_stable_for_same_content():
    text = "Check scheduler heartbeat"

    assert generate_chunk_uid("Airflow Troubleshooting", "Scheduler Heartbeat", text) == generate_chunk_uid(
        "Airflow Troubleshooting", "Scheduler Heartbeat", text
    )


def test_detect_language_classifies_english_chinese_and_mixed():
    assert detect_language("scheduler heartbeat timeout") == "en"
    assert detect_language("调度器心跳超时，需要检查日志") == "zh"
    assert detect_language("Airflow 调度器 heartbeat timeout") == "mixed"


def test_chunk_document_preserves_metadata_and_bounds():
    chunks = chunk_document(_parsed_document(), chunk_size=80, chunk_overlap=10, min_chunk_size=5, max_chunk_size=120)

    assert chunks
    assert all(chunk.chunk_uid.startswith("airflow-troubleshooting:scheduler-heartbeat:") for chunk in chunks)
    assert all(chunk.token_count <= 120 for chunk in chunks)
    assert any(chunk.metadata.get("contains_code") for chunk in chunks)
    assert all(chunk.section_path == "Airflow Troubleshooting > Scheduler Heartbeat" for chunk in chunks)


def test_chunk_document_splits_large_blocks_with_overlap_without_tail_duplicate(monkeypatch):
    words = [f"word{i}" for i in range(30)]
    parsed = ParsedDocument(
        title="Long Block",
        file_name="long.md",
        content_type="text/markdown",
        parser_name="test",
        parser_version="1.0",
        byte_size=256,
        blocks=[
            ParsedBlock(
                text=" ".join(words),
                block_type="paragraph",
                section_path="Long Block",
                source_anchor="long-block",
            )
        ],
    )

    monkeypatch.setattr(chunker_module, "_encoding", lambda: None)

    chunks = chunk_document(parsed, chunk_size=10, chunk_overlap=2, min_chunk_size=1, max_chunk_size=12)

    assert [chunk.content.split() for chunk in chunks] == [
        words[0:10],
        words[8:18],
        words[16:26],
        words[24:30],
    ]


def test_model_router_rejects_unknown_purpose():
    with pytest.raises(ValueError, match="Unknown model purpose"):
        get_model_name("creative")


async def test_embed_batch_uses_content_cache(monkeypatch):
    cached_vector = [0.1] * 2048

    async def fake_get_json(key):
        return cached_vector

    async def fail_embed_inputs(texts):
        raise AssertionError("API should not be called when cache hits")

    monkeypatch.setattr("src.document.embedder._redis_get_json", fake_get_json)
    monkeypatch.setattr("src.document.embedder._embed_inputs", fail_embed_inputs)

    assert await embed_batch(["cached text"]) == [cached_vector]


async def test_embed_with_cache_uses_query_key_and_ttl(monkeypatch):
    vector = [0.3] * embedder_module.get_embedding_dim()
    reads: list[str] = []
    writes: list[tuple[str, list[float], int]] = []

    async def fake_get_json(key):
        reads.append(key)
        return None

    async def fake_set_json(key, value, ttl):
        writes.append((key, value, ttl))

    async def fake_embed_inputs(texts):
        assert texts == ["cache this query"]
        return [vector]

    monkeypatch.setattr(embedder_module, "_redis_get_json", fake_get_json)
    monkeypatch.setattr(embedder_module, "_redis_set_json", fake_set_json)
    monkeypatch.setattr(embedder_module, "_embed_inputs", fake_embed_inputs)

    assert await embedder_module.embed_with_cache("cache this query", ttl=123) == vector

    expected_hash = hashlib.sha256(b"cache this query").hexdigest()[:16]
    assert reads == [f"cache:query_embedding:{expected_hash}"]
    assert writes == [(f"cache:query_embedding:{expected_hash}", vector, 123)]


async def test_embed_batch_uses_content_key_and_24h_ttl(monkeypatch):
    vector = [0.4] * embedder_module.get_embedding_dim()
    writes: list[tuple[str, list[float], int]] = []

    async def fake_get_json(key):
        return None

    async def fake_set_json(key, value, ttl):
        writes.append((key, value, ttl))

    async def fake_embed_inputs(texts):
        assert texts == ["cache this chunk"]
        return [vector]

    monkeypatch.setattr(embedder_module, "_redis_get_json", fake_get_json)
    monkeypatch.setattr(embedder_module, "_redis_set_json", fake_set_json)
    monkeypatch.setattr(embedder_module, "_embed_inputs", fake_embed_inputs)

    assert await embedder_module.embed_batch(["cache this chunk"]) == [vector]

    expected_hash = hashlib.sha256(b"cache this chunk").hexdigest()[:16]
    assert writes == [
        (f"cache:embedding:{embedder_module.settings.embedding_model}:{expected_hash}", vector, 86400)
    ]


async def test_embed_query_retries_retryable_embedding_errors(monkeypatch):
    calls = {"count": 0}
    sleeps: list[float] = []

    class FakeEmbeddings:
        async def create(self, **kwargs):
            assert kwargs["dimensions"] == embedder_module.get_embedding_dim()
            calls["count"] += 1
            if calls["count"] == 1:
                raise embedder_module.RetryableError("temporary embedding outage", backoff_seconds=2.0)
            return SimpleNamespace(
                data=[SimpleNamespace(index=0, embedding=[0.2] * embedder_module.get_embedding_dim())]
            )

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(
        embedder_module,
        "_embedding_client",
        lambda: (SimpleNamespace(embeddings=FakeEmbeddings()), "text-embedding-v4"),
    )
    monkeypatch.setattr(embedder_module.asyncio, "sleep", fake_sleep)

    assert await embedder_module.embed_query("retryable text") == [0.2] * embedder_module.get_embedding_dim()
    assert calls["count"] == 2
    assert sleeps == [2.0]


async def test_embed_batch_clamps_to_provider_batch_limit(monkeypatch):
    batches: list[list[str]] = []

    async def fake_get_json(key):
        return None

    async def fake_set_json(key, value, ttl):
        return None

    async def fake_embed_inputs(texts):
        batches.append(list(texts))
        return [[0.5] * embedder_module.get_embedding_dim() for _ in texts]

    monkeypatch.setattr(embedder_module, "_redis_get_json", fake_get_json)
    monkeypatch.setattr(embedder_module, "_redis_set_json", fake_set_json)
    monkeypatch.setattr(embedder_module, "_embed_inputs", fake_embed_inputs)

    result = await embedder_module.embed_batch([f"text-{i}" for i in range(12)], batch_size=20)

    assert len(result) == 12
    assert [len(batch) for batch in batches] == [10, 2]


async def test_chat_completion_falls_back_from_fast_to_pro(monkeypatch):
    called_models: list[str] = []

    class FailingCompletions:
        async def create(self, **kwargs):
            called_models.append(kwargs["model"])
            raise RuntimeError("primary model unavailable")

    class SucceedingCompletions:
        async def create(self, **kwargs):
            called_models.append(kwargs["model"])
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="fallback response"))],
                usage=SimpleNamespace(prompt_tokens=3, completion_tokens=4),
            )

    def fake_client_for(model):
        if model in (None, "fast"):
            return SimpleNamespace(chat=SimpleNamespace(completions=FailingCompletions())), "fast-model"
        return SimpleNamespace(chat=SimpleNamespace(completions=SucceedingCompletions())), "pro-model"

    monkeypatch.setattr(llm_client, "_client_for", fake_client_for)

    result = await llm_client.chat_completion([{"role": "user", "content": "hello"}])

    assert result == {"content": "fallback response", "usage": {"prompt_tokens": 3, "completion_tokens": 4}}
    assert called_models == ["fast-model", "pro-model"]
