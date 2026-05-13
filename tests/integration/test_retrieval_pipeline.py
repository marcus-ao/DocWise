"""Integration tests — 6 smoke queries covering all 5 routes + 1 degradation."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.agent.state import (
    create_initial_state,
)


def _mock_chunks(n: int = 3, rerank_score: float = 0.8) -> list[dict]:
    return [
        {
            "chunk_id": f"chunk-{i}",
            "chunk_uid": f"doc:section:hash{i}",
            "content": f"This is test content for chunk {i}. It contains relevant information.",
            "document_title": f"Test Document {i}",
            "section_path": f"Section > Sub {i}",
            "workspace_id": "ws-uuid-1",
            "page_number": i,
            "doc_type": "tech_doc",
            "document_id": f"doc-{i}",
            "vector_score": 0.9 - i * 0.1,
            "keyword_score": 0.7 - i * 0.1,
            "rrf_score": 0.03 - i * 0.005,
            "rerank_score": rerank_score - i * 0.1,
            "final_rank": i + 1,
        }
        for i in range(n)
    ]


def _patch_all():
    """Return a dict of patches for external dependencies."""
    return {
        "session": patch("src.agent.nodes.scope_selector.async_session_factory", new_callable=MagicMock),
        "embed": patch("src.agent.nodes.hybrid_retriever.embed_with_cache", new_callable=AsyncMock),
        "vector": patch("src.agent.nodes.hybrid_retriever.vector_store"),
        "keyword": patch("src.agent.nodes.hybrid_retriever.keyword_search"),
        "resolve_ws": patch("src.agent.nodes.hybrid_retriever.resolve_workspace_ids", new_callable=AsyncMock),
        "reranker": patch("src.retrieval.reranker._call_dashscope_rerank", new_callable=AsyncMock),
        "chat": patch("src.llm.client.AsyncOpenAI"),
    }


# ============================================================
# Smoke 1: tech_general
# ============================================================


class TestTechGeneral:
    @pytest.mark.asyncio
    async def test_tech_general_route(self):
        """tech_general query routes correctly and sets public_only policy."""
        from src.agent.nodes.query_router import query_router

        state = create_initial_state("What is FastAPI dependency injection?", trace_id="run-1")
        llm_resp = {
            "content": json.dumps({
                "route": "tech_general", "confidence": 0.85,
                "workspace_policy": "public_only", "needs_tools": False,
                "key_entities": ["FastAPI"], "reason": "general tech",
            }),
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }
        with patch("src.agent.nodes.query_router.chat_completion", new_callable=AsyncMock, return_value=llm_resp):
            result = await query_router(state)
        assert result["route"] == "tech_general"
        assert result["workspace_policy"] == "public_only"


# ============================================================
# Smoke 2: project_specific
# ============================================================


class TestProjectSpecific:
    @pytest.mark.asyncio
    async def test_project_specific_route(self):
        from src.agent.nodes.query_router import query_router

        state = create_initial_state("我们 Airflow 服务的 SLA 是多少？", trace_id="run-2")
        result = await query_router(state)
        assert result["route"] == "project_specific"
        assert result["workspace_policy"] == "selected_project_plus_public"


# ============================================================
# Smoke 3: troubleshooting
# ============================================================


class TestTroubleshooting:
    @pytest.mark.asyncio
    async def test_troubleshooting_route_triggers_tools(self):
        from src.agent.nodes.query_router import query_router

        state = create_initial_state("Airflow task 一直失败怎么办？", trace_id="run-3")
        result = await query_router(state)
        assert result["route"] == "troubleshooting"
        assert result["workspace_policy"] == "selected_project_plus_public"

    @pytest.mark.asyncio
    async def test_troubleshooting_tool_planner_selects_tools(self):
        from src.agent.nodes.tool_planner import tool_planner

        state = create_initial_state("Airflow task 一直失败怎么办？", trace_id="run-3")
        state["route"] = "troubleshooting"
        state["key_entities"] = ["airflow-scheduler"]
        state["selected_project"] = "project_airflow"
        state["rewritten_query"] = state["original_query"]

        llm_resp = {
            "content": json.dumps({
                "tool_params": {
                    "query_project_manifest": {"project_name": "data-platform"},
                    "query_service_status": {"service_name": "airflow-scheduler"},
                    "query_mock_logs": {
                        "service_name": "airflow-scheduler",
                        "level": "ERROR",
                        "time_range": "last_30m",
                        "keywords": ["fail"],
                    },
                }
            }),
            "usage": {"prompt_tokens": 10, "completion_tokens": 30},
        }
        with patch("src.agent.nodes.tool_planner.chat_completion", new_callable=AsyncMock, return_value=llm_resp):
            result = await tool_planner(state)
        assert "query_project_manifest" in result["tools_to_call"]
        assert "query_service_status" in result["tools_to_call"]
        assert "query_mock_logs" in result["tools_to_call"]

    @pytest.mark.asyncio
    async def test_tool_planner_repairs_blank_service_name(self):
        from src.agent.nodes.tool_planner import tool_planner

        state = create_initial_state("Airflow task 失败怎么排查？", trace_id="run-blank-service")
        state["route"] = "troubleshooting"
        state["rewritten_query"] = "Airflow task 失败排查方法"

        llm_resp = {
            "content": json.dumps({
                "tool_params": {
                    "query_project_manifest": {"project_name": "", "service_name": ""},
                    "query_service_status": {"service_name": ""},
                    "query_mock_logs": {
                        "service_name": "",
                        "level": "ERROR",
                        "time_range": "last_30m",
                        "keywords": ["task failed"],
                    },
                }
            }),
            "usage": {"prompt_tokens": 10, "completion_tokens": 30},
        }
        with patch("src.agent.nodes.tool_planner.chat_completion", new_callable=AsyncMock, return_value=llm_resp):
            result = await tool_planner(state)

        assert result["tool_params"]["query_project_manifest"]["service_name"] == "airflow"
        assert result["tool_params"]["query_service_status"]["service_name"] == "airflow"
        assert result["tool_params"]["query_mock_logs"]["service_name"] == "airflow"

    @pytest.mark.asyncio
    async def test_hybrid_retriever_uses_effective_query(self):
        from src.agent.nodes.hybrid_retriever import hybrid_retriever

        state = create_initial_state("原始问题", trace_id="run-effective-query")
        state["workspace_ids"] = ["public_tech"]
        state["effective_query"] = "effective rewritten query"

        mock_session = AsyncMock()
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
        seen: dict[str, object] = {}

        async def fake_embed(query: str):
            seen["embed_query"] = query
            return [0.1] * 4

        async def fake_vector(_db, _embedding, _workspace_ids, top_k: int):
            seen["vector_top_k"] = top_k
            return []

        async def fake_keyword(_db, query: str, _workspace_ids, top_k: int):
            seen["keyword_query"] = query
            return []

        with (
            patch("src.agent.nodes.hybrid_retriever.async_session_factory", return_value=mock_session_ctx),
            patch("src.agent.nodes.hybrid_retriever.resolve_workspace_ids", AsyncMock(return_value=[uuid4()])),
            patch("src.agent.nodes.hybrid_retriever.embed_with_cache", fake_embed),
            patch("src.agent.nodes.hybrid_retriever.vector_store.search", fake_vector),
            patch("src.agent.nodes.hybrid_retriever.keyword_search.search", fake_keyword),
        ):
            await hybrid_retriever(state)

        assert seen["embed_query"] == "effective rewritten query"
        assert seen["keyword_query"] == "effective rewritten query"

    @pytest.mark.asyncio
    async def test_reranker_uses_effective_query(self):
        from src.agent.nodes.reranker import reranker_node

        state = create_initial_state("原始问题", trace_id="run-reranker-effective-query")
        state["effective_query"] = "effective rerank query"
        state["retrieved_chunks"] = _mock_chunks(2)
        seen: dict[str, object] = {}

        async def fake_rerank(query: str, chunks: list[dict], top_k: int):
            seen["query"] = query
            seen["top_k"] = top_k
            return chunks[:top_k], False

        with patch("src.agent.nodes.reranker.reranker.rerank", fake_rerank):
            await reranker_node(state)

        assert seen["query"] == "effective rerank query"


# ============================================================
# Smoke 4: runbook_generation
# ============================================================


class TestRunbookGeneration:
    @pytest.mark.asyncio
    async def test_runbook_route(self):
        from src.agent.nodes.query_router import query_router

        state = create_initial_state("给 Airflow scheduler 故障写一个 runbook", trace_id="run-4")
        result = await query_router(state)
        assert result["route"] == "runbook_generation"


# ============================================================
# Smoke 5: out_of_scope → refusal
# ============================================================


class TestOutOfScope:
    @pytest.mark.asyncio
    async def test_out_of_scope_refuses(self):
        from src.agent.nodes.query_router import query_router
        from src.agent.nodes.refusal_checker import refusal_checker

        state = create_initial_state("帮我预测明天股票走势", trace_id="run-5")
        state = await query_router(state)
        assert state["route"] == "out_of_scope"

        state["reranked_chunks"] = []
        state["evidence_sufficient"] = False
        result = await refusal_checker(state)
        assert result["refused"] is True
        assert result["refusal_reason"] == "out_of_scope"
        assert result["citations"] == []


# ============================================================
# Smoke 6: degradation — reranker fallback
# ============================================================


class TestDegradation:
    @pytest.mark.asyncio
    async def test_reranker_fallback_uses_rrf_scores(self):
        from src.retrieval.reranker import _fallback

        chunks = [
            {"chunk_id": "a", "rrf_score": 0.03, "content": "chunk a"},
            {"chunk_id": "b", "rrf_score": 0.05, "content": "chunk b"},
            {"chunk_id": "c", "rrf_score": 0.01, "content": "chunk c"},
        ]
        result, fallback_used = _fallback(chunks, top_k=2)
        assert fallback_used is True
        assert len(result) == 2
        assert result[0]["chunk_id"] == "b"
        assert result[1]["chunk_id"] == "a"
        assert result[0]["final_rank"] == 1
        assert result[1]["final_rank"] == 2

    @pytest.mark.asyncio
    async def test_reranker_api_failure_triggers_fallback(self):
        from src.retrieval.reranker import rerank

        chunks = [
            {"chunk_id": "a", "rrf_score": 0.05, "content": "chunk a"},
            {"chunk_id": "b", "rrf_score": 0.03, "content": "chunk b"},
        ]
        with patch("src.retrieval.reranker.get_provider_config", side_effect=Exception("API down")):
            result, fallback = await rerank("test query", chunks, top_k=2)
        assert fallback is True
        assert len(result) == 2
        assert result[0]["chunk_id"] == "a"


# ============================================================
# Evidence + Citation integration
# ============================================================


class TestEvidenceCitation:
    @pytest.mark.asyncio
    async def test_evidence_validator_sufficient(self):
        from src.agent.nodes.evidence_validator import evidence_validator

        state = create_initial_state("test", trace_id="run-ev")
        state["reranked_chunks"] = _mock_chunks(3, rerank_score=0.8)
        result = await evidence_validator(state)
        assert result["evidence_sufficient"] is True

    @pytest.mark.asyncio
    async def test_evidence_validator_insufficient(self):
        from src.agent.nodes.evidence_validator import evidence_validator

        state = create_initial_state("test", trace_id="run-ev2")
        state["reranked_chunks"] = _mock_chunks(1, rerank_score=0.1)
        result = await evidence_validator(state)
        assert result["evidence_sufficient"] is False

    @pytest.mark.asyncio
    async def test_citation_verifier_valid(self):
        from src.agent.nodes.citation_verifier import citation_verifier

        state = create_initial_state("test", trace_id="run-cv")
        state["reranked_chunks"] = _mock_chunks(3)
        state["answer"] = "According to [1] and [2], the issue is clear."
        state["confidence_score"] = 0.8
        result = await citation_verifier(state)
        assert len(result["citations"]) == 2
        assert result["citations"][0]["index"] == 1
        assert result["citations"][1]["index"] == 2

    @pytest.mark.asyncio
    async def test_citation_quote_preserves_full_chunk_content(self):
        from src.agent.nodes.citation_verifier import citation_verifier

        full_content = "Confirm scheduler health. Review worker logs for DB_TIMEOUT or OOM. Check retry configuration."
        state = create_initial_state("test", trace_id="run-cv-full-quote")
        state["reranked_chunks"] = [
            {
                "chunk_id": "chunk-1",
                "chunk_uid": "doc:section:hash1",
                "content": full_content,
                "document_title": "Guide",
                "section_path": "Task Failure",
                "workspace_id": "ws-1",
                "document_id": "doc-1",
                "rerank_score": 0.8,
                "final_rank": 1,
            }
        ]
        state["answer"] = "Check the runbook [1]."

        result = await citation_verifier(state)

        assert result["citations"][0]["quote"] == full_content

    @pytest.mark.asyncio
    async def test_citation_verifier_removes_invalid(self):
        from src.agent.nodes.citation_verifier import citation_verifier

        state = create_initial_state("test", trace_id="run-cv2")
        state["reranked_chunks"] = _mock_chunks(2)
        state["answer"] = "See [1] and [99] for details."
        state["confidence_score"] = 0.8
        result = await citation_verifier(state)
        assert len(result["citations"]) == 1
        assert "[99]" not in result["answer"]

    @pytest.mark.asyncio
    async def test_citation_all_invalid_reduces_confidence(self):
        from src.agent.nodes.citation_verifier import citation_verifier

        state = create_initial_state("test", trace_id="run-cv3")
        state["reranked_chunks"] = _mock_chunks(2)
        state["answer"] = "See [99] and [100] for details."
        state["confidence_score"] = 0.8
        result = await citation_verifier(state)
        assert len(result["citations"]) == 0
        assert result["confidence_score"] == pytest.approx(0.4)
