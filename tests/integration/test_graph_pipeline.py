"""Graph-level integration tests — exercise full LangGraph pipeline end-to-end.

Covers:
- query routing → scope selection → retrieval fallback → reranker fallback
- tool loop execution
- final refusal/answer state transitions
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.graph import build_agent_graph
from src.agent.state import RetryBudget, create_initial_state
from src.models.base import WorkspaceType


def _mock_workspace(
    ws_id: str,
    name: str,
    *,
    workspace_type: WorkspaceType,
    project_name: str | None = None,
    slug: str = "",
):
    """Create a mock Workspace ORM object."""
    ws = MagicMock()
    ws.id = ws_id
    ws.name = name
    ws.project_name = project_name
    ws.slug = slug or name
    ws.workspace_type = workspace_type
    ws.is_active = True
    return ws


class _Rows:
    def __init__(self, items: list[object]) -> None:
        self._items = items

    def all(self) -> list[object]:
        return list(self._items)


class _ScopeSession:
    def __init__(self, workspaces: list[object]) -> None:
        self._workspaces = workspaces

    async def scalars(self, stmt: object) -> _Rows:
        return _Rows(self._workspaces)


class _ScopeSessionContext:
    def __init__(self, workspaces: list[object]) -> None:
        self._session = _ScopeSession(workspaces)

    async def __aenter__(self) -> _ScopeSession:
        return self._session

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


def _mock_chunks(n: int = 3) -> list[dict]:
    return [
        {
            "chunk_id": f"chunk-{i}",
            "chunk_uid": f"doc:section:hash{i}",
            "content": f"Relevant content for chunk {i}. Contains useful information.",
            "document_title": f"Doc {i}",
            "section_path": f"Section {i}",
            "workspace_id": "ws-1",
            "page_number": i,
            "doc_type": "tech_doc",
            "document_id": f"doc-{i}",
            "vector_score": 0.9 - i * 0.05,
            "keyword_score": 0.7 - i * 0.05,
            "rrf_score": 0.03 - i * 0.005,
        }
        for i in range(n)
    ]


def _mock_reranked(chunks: list[dict]) -> list[dict]:
    for i, c in enumerate(chunks):
        c["rerank_score"] = 0.9 - i * 0.1
        c["final_rank"] = i + 1
    return chunks


# ============================================================
# Test 1: Troubleshooting route — full pipeline with tool loop
# ============================================================


class TestTroubleshootingFullPipeline:
    """Troubleshooting query exercises: routing → scope → retrieval → rerank → tools → answer."""

    @pytest.mark.asyncio
    async def test_troubleshooting_end_to_end(self):
        graph = build_agent_graph()
        state = create_initial_state("Airflow scheduler 一直 fail 怎么办？", trace_id="graph-ts-1")

        chunks = _mock_chunks(3)
        # Low rerank scores → evidence insufficient → triggers tool loop
        reranked = chunks.copy()
        for i, c in enumerate(reranked):
            c["rerank_score"] = 0.1 - i * 0.02  # all below EVIDENCE_MIN_RERANK_SCORE (0.3)
            c["final_rank"] = i + 1

        # scope_selector helpers
        scope_workspaces = [
            _mock_workspace(
                "ws-1",
                "Airflow Workspace",
                workspace_type=WorkspaceType.project_pack,
                project_name="data-platform",
                slug="project_airflow",
            ),
            _mock_workspace(
                "ws-pub",
                "Public Tech",
                workspace_type=WorkspaceType.public_tech,
                slug="public_tech",
            ),
            _mock_workspace(
                "ws-mock",
                "Mock Ops",
                workspace_type=WorkspaceType.mock_ops,
                slug="mock_ops",
            ),
        ]

        # hybrid_retriever mocks
        mock_session_ctx = AsyncMock()
        mock_session = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
        scope_session_ctx = _ScopeSessionContext(scope_workspaces)

        mock_embed = AsyncMock(return_value=[0.1] * 2048)
        mock_vector = AsyncMock(return_value=chunks[:2])
        mock_keyword = AsyncMock(return_value=chunks[1:])
        mock_resolve_ws = AsyncMock(return_value=["ws-1", "ws-pub"])

        # Reranker
        mock_rerank = AsyncMock(return_value=(reranked, False))
        # query_rewriter LLM
        rewriter_resp = {
            "content": "Airflow scheduler fail troubleshooting",
            "usage": {"prompt_tokens": 10, "completion_tokens": 10},
        }

        # Answer generator
        async def mock_stream_factory(*args, **kwargs):
            for token in ["Based on [1]", ", the issue is", " scheduler OOM."]:
                yield token

        mock_stream_fn = MagicMock(side_effect=lambda *a, **kw: mock_stream_factory(*a, **kw))

        # Tool mocks
        mock_tools = {
            "search_docs": AsyncMock(return_value={"chunks": []}),
            "query_project_manifest": AsyncMock(return_value={
                "matched_services": [{"service_name": "airflow-scheduler"}],
                "dependencies": [], "runbooks": [], "confidence": 1.0,
            }),
            "query_service_status": AsyncMock(return_value={
                "service_name": "airflow-scheduler", "status": "degraded",
                "metrics": {"cpu_percent": 0, "memory_percent": 0,
                            "error_rate_5m": 0, "p95_latency_ms": 0},
                "active_alerts": [], "checked_at": "",
            }),
            "query_mock_logs": AsyncMock(return_value={
                "service_name": "airflow-scheduler", "time_range": "last_30m",
                "matched_count": 2, "entries": [], "summary": "OOM errors",
            }),
            "generate_runbook_draft": AsyncMock(return_value={
                "title": "", "severity": "", "symptoms": [],
                "diagnosis_steps": [], "mitigation_steps": [],
                "rollback_steps": [], "citations": [],
            }),
        }

        # tool_planner LLM
        tool_planner_resp = {
            "content": json.dumps({"tool_params": {
                "query_project_manifest": {"project_name": "data-platform"},
                "query_service_status": {"service_name": "airflow-scheduler"},
                "query_mock_logs": {"service_name": "airflow-scheduler", "time_range": "last_30m"},
            }}),
            "usage": {"prompt_tokens": 10, "completion_tokens": 30},
        }

        with (
            patch("src.agent.nodes.scope_selector.async_session_factory", return_value=scope_session_ctx),
            patch("src.agent.rewriter.runtime.chat_completion", new_callable=AsyncMock, return_value=rewriter_resp),
            patch("src.agent.nodes.hybrid_retriever.async_session_factory", return_value=mock_session_ctx),
            patch("src.agent.nodes.hybrid_retriever.embed_with_cache", mock_embed),
            patch("src.agent.nodes.hybrid_retriever.vector_store.search", mock_vector),
            patch("src.agent.nodes.hybrid_retriever.keyword_search.search", mock_keyword),
            patch("src.agent.nodes.hybrid_retriever.resolve_workspace_ids", mock_resolve_ws),
            patch("src.retrieval.reranker.rerank", mock_rerank),
            patch(
                "src.agent.nodes.tool_planner.chat_completion",
                new_callable=AsyncMock, return_value=tool_planner_resp,
            ),
            patch("src.agent.nodes.tool_executor._get_tool_registry", return_value=mock_tools),
            patch("src.agent.nodes.answer_generator.chat_completion_stream", mock_stream_fn),
        ):
            config = {"configurable": {"retry_budget": RetryBudget(3)}}
            result = await graph.ainvoke(state, config=config)

        assert result["route"] == "troubleshooting"
        assert result["tool_loop_count"] >= 1
        assert len(result["tool_results"]) > 0
        assert result["answer"] != ""
        assert result["refused"] is False


# ============================================================
# Test 2: Out-of-scope → refusal path (no retrieval, no tools)
# ============================================================


class TestOutOfScopeRefusal:
    """Out-of-scope query skips retrieval and tools, goes straight to refusal."""

    @pytest.mark.asyncio
    async def test_out_of_scope_refuses_cleanly(self):
        graph = build_agent_graph()
        state = create_initial_state("帮我预测明天股票走势", trace_id="graph-oos-1")

        scope_session_ctx = _ScopeSessionContext(
            [
                _mock_workspace(
                    "ws-pub",
                    "Public Tech",
                    workspace_type=WorkspaceType.public_tech,
                    slug="public_tech",
                )
            ]
        )

        with (
            patch("src.agent.nodes.scope_selector.async_session_factory", return_value=scope_session_ctx),
        ):
            config = {"configurable": {"retry_budget": RetryBudget(3)}}
            result = await graph.ainvoke(state, config=config)

        assert result["route"] == "out_of_scope"
        assert result["refused"] is True
        assert result["refusal_reason"] == "out_of_scope"
        assert result["workspace_ids"] == []
        assert result["tool_results"] == []
        assert result["retrieved_chunks"] == []


# ============================================================
# Test 3: Retrieval fallback — both vector and keyword fail
# ============================================================


class TestRetrievalFallback:
    """When both retrieval paths fail, pipeline degrades gracefully."""

    @pytest.mark.asyncio
    async def test_both_retrieval_fail_degrades(self):
        graph = build_agent_graph()
        state = create_initial_state("What is FastAPI middleware?", trace_id="graph-rf-1")

        # Route via LLM to tech_general
        router_resp = {
            "content": json.dumps({
                "route": "tech_general", "confidence": 0.8,
                "workspace_policy": "public_only", "needs_tools": False,
                "key_entities": ["FastAPI"], "reason": "general tech",
            }),
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }

        # scope_selector
        scope_session_ctx = _ScopeSessionContext(
            [
                _mock_workspace(
                    "ws-pub",
                    "Public Tech",
                    workspace_type=WorkspaceType.public_tech,
                    slug="public_tech",
                )
            ]
        )
        mock_session_ctx = AsyncMock()
        mock_session = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_resolve_ws = AsyncMock(return_value=["ws-pub"])
        mock_embed = AsyncMock(side_effect=Exception("embedding service down"))
        mock_keyword_fail = AsyncMock(side_effect=Exception("keyword service down"))

        # Reranker — will get empty input
        mock_rerank = AsyncMock(return_value=([], False))

        # query_rewriter
        rewriter_resp = {
            "content": "FastAPI middleware explanation",
            "usage": {"prompt_tokens": 10, "completion_tokens": 10},
        }

        # Answer generator with no evidence
        async def mock_stream(*args, **kwargs):
            yield "I don't have enough information to answer this question."

        with (
            patch("src.agent.nodes.query_router.chat_completion", new_callable=AsyncMock, return_value=router_resp),
            patch("src.agent.nodes.scope_selector.async_session_factory", return_value=scope_session_ctx),
            patch("src.agent.rewriter.runtime.chat_completion", new_callable=AsyncMock, return_value=rewriter_resp),
            patch("src.agent.nodes.hybrid_retriever.async_session_factory", return_value=mock_session_ctx),
            patch("src.agent.nodes.hybrid_retriever.embed_with_cache", mock_embed),
            patch("src.agent.nodes.hybrid_retriever.keyword_search.search", mock_keyword_fail),
            patch("src.agent.nodes.hybrid_retriever.resolve_workspace_ids", mock_resolve_ws),
            patch("src.retrieval.reranker.rerank", mock_rerank),
            patch("src.agent.nodes.answer_generator.chat_completion_stream", return_value=mock_stream()),
        ):
            config = {"configurable": {"retry_budget": RetryBudget(3)}}
            result = await graph.ainvoke(state, config=config)

        assert result["route"] == "tech_general"
        assert result["retrieved_chunks"] == []
        assert result["evidence_sufficient"] is False
        assert result["answer"] != "" or result["refused"] is True
        assert result["error"] is not None


# ============================================================
# Test 4: Reranker fallback — reranker fails, uses RRF ordering
# ============================================================


class TestRerankerFallback:
    """When reranker API fails, pipeline uses RRF scores as fallback."""

    @pytest.mark.asyncio
    async def test_reranker_failure_uses_rrf(self):
        graph = build_agent_graph()
        state = create_initial_state("我们项目的 SLA 是多少？", trace_id="graph-rr-1")

        state["selected_workspace_slug"] = "project_airflow"
        chunks = _mock_chunks(4)

        # scope_selector
        scope_session_ctx = _ScopeSessionContext(
            [
                _mock_workspace(
                    "ws-proj",
                    "Airflow Workspace",
                    workspace_type=WorkspaceType.project_pack,
                    project_name="data-platform",
                    slug="project_airflow",
                ),
                _mock_workspace(
                    "ws-pub",
                    "Public Tech",
                    workspace_type=WorkspaceType.public_tech,
                    slug="public_tech",
                ),
            ]
        )

        mock_session_ctx = AsyncMock()
        mock_session = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_resolve_ws = AsyncMock(return_value=["ws-proj"])
        mock_embed = AsyncMock(return_value=[0.1] * 2048)
        mock_vector = AsyncMock(return_value=chunks[:2])
        mock_keyword = AsyncMock(return_value=chunks[2:])

        # query_rewriter
        rewriter_resp = {
            "content": "项目 SLA 查询",
            "usage": {"prompt_tokens": 10, "completion_tokens": 10},
        }

        # Reranker fails — returns fallback
        fallback_chunks = sorted(chunks, key=lambda c: c["rrf_score"], reverse=True)
        for i, c in enumerate(fallback_chunks):
            c["rerank_score"] = c["rrf_score"]
            c["final_rank"] = i + 1
        mock_rerank = AsyncMock(return_value=(fallback_chunks[:3], True))

        async def mock_stream(*args, **kwargs):
            yield "According to [1], the SLA is 99.9%."

        with (
            patch("src.agent.nodes.scope_selector.async_session_factory", return_value=scope_session_ctx),
            patch("src.agent.rewriter.runtime.chat_completion", new_callable=AsyncMock, return_value=rewriter_resp),
            patch("src.agent.nodes.hybrid_retriever.async_session_factory", return_value=mock_session_ctx),
            patch("src.agent.nodes.hybrid_retriever.embed_with_cache", mock_embed),
            patch("src.agent.nodes.hybrid_retriever.vector_store.search", mock_vector),
            patch("src.agent.nodes.hybrid_retriever.keyword_search.search", mock_keyword),
            patch("src.agent.nodes.hybrid_retriever.resolve_workspace_ids", mock_resolve_ws),
            patch("src.retrieval.reranker.rerank", mock_rerank),
            patch("src.agent.nodes.answer_generator.chat_completion_stream", return_value=mock_stream()),
        ):
            config = {"configurable": {"retry_budget": RetryBudget(3)}}
            result = await graph.ainvoke(state, config=config)

        assert result["route"] == "project_specific"
        assert len(result["reranked_chunks"]) > 0
        assert result["answer"] != ""
        assert result["refused"] is False
