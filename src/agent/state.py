"""AgentState TypedDict, thresholds, RetryBudget, exception classes, and safe_node wrapper."""
from __future__ import annotations

import asyncio
from typing import Literal, TypedDict

import structlog

from src.common.exceptions import NonRetryableError, RetryableError, ToolExecutionError

__all__ = [
    "AgentState",
    "NonRetryableError",
    "RetryBudget",
    "RetryableError",
    "ToolExecutionError",
    "create_initial_state",
    "safe_node",
]

logger = structlog.get_logger(__name__)


# ============================================================
# AgentState
# ============================================================

class AgentState(TypedDict):
    """LangGraph Agent workflow global state. One instance per Agent run."""

    # Input
    original_query: str
    rewritten_query: str
    effective_query: str
    conversation_id: str
    turn_index: int
    parent_run_id: str | None
    recent_turns: list[dict]
    context_summary: str | None

    # Routing
    route: Literal[
        "tech_general",
        "project_specific",
        "troubleshooting",
        "runbook_generation",
        "out_of_scope",
    ]
    route_confidence: float
    workspace_policy: Literal[
        "public_only",
        "selected_project_plus_public",
        "none",
    ]
    workspace_ids: list[str]
    selected_project: str | None
    selected_workspace_slug: str | None
    display_workspace_slug: str | None
    effective_workspace_slugs: list[str]
    scope_reason_code: str | None
    scope_reason_params: dict | None
    workspace_alias_hits: list[str]
    key_entities: list[str]

    # Retrieval
    retrieved_chunks: list[dict]
    reranked_chunks: list[dict]

    # Evidence
    evidence_sufficient: bool

    # Tool calls
    tools_to_call: list[str]
    tool_params: dict[str, dict]  # per-tool parameters planned by tool_planner
    tool_results: list[dict]
    latest_tool_results: list[dict]  # latest round only, for SSE streaming
    tool_loop_count: int
    working_context_preview: dict | None
    working_context_diagnostics: dict | None

    # Generation
    answer: str
    citations: list[dict]
    confidence_score: float
    refused: bool
    refusal_reason: str | None

    # Tracing
    trace_id: str
    query_id: str
    error: str | None


# ============================================================
# Threshold constants
# ============================================================

EVIDENCE_MIN_CHUNKS: int = 1
EVIDENCE_MIN_RERANK_SCORE: float = 0.3
EVIDENCE_MIN_RRF_SCORE: float = 0.05

REFUSAL_CONFIDENCE_THRESHOLD: float = 0.6
REFUSAL_NO_EVIDENCE_THRESHOLD: int = 0

TOOL_LOOP_MAX_ROUNDS: int = 2
TOOL_MAX_CALLS_PER_RUN: int = 5
TOOL_MAX_CALLS_PER_TOOL: int = 2

RETRIEVAL_VECTOR_TOP_K: int = 20
RETRIEVAL_KEYWORD_TOP_K: int = 20
RETRIEVAL_RRF_K: int = 60
RERANK_TOP_K: int = 5


# ============================================================
# RetryBudget
# ============================================================


class RetryBudget:
    """Global retry budget shared across all nodes in a single Agent run."""

    def __init__(self, max_total_retries: int = 3) -> None:
        self._max = max_total_retries
        self._used = 0

    def can_retry(self) -> bool:
        return self._used < self._max

    def consume(self) -> None:
        self._used += 1

    @property
    def remaining(self) -> int:
        return self._max - self._used


# ============================================================
# safe_node wrapper
# ============================================================


def safe_node(func, retry_budget: RetryBudget | None = None):
    """Wrap a node function with retry + degradation logic.

    If *retry_budget* is ``None`` the wrapper reads it from
    ``config["configurable"]["retry_budget"]`` at call time so that
    each Agent run gets its own budget instance.
    """

    async def wrapper(state: AgentState, config=None) -> AgentState:  # type: ignore[assignment]
        budget = retry_budget
        if budget is None and config:
            budget = config.get("configurable", {}).get("retry_budget")

        try:
            return await func(state, config=config)
        except RetryableError as exc:
            if budget and budget.can_retry():
                budget.consume()
                await asyncio.sleep(exc.backoff_seconds)
                try:
                    return await func(state, config=config)
                except Exception as retry_err:
                    _append_error(state, f"{func.__name__} retry failed: {retry_err}")
                    return state
            _append_error(state, f"{func.__name__} failed, retry budget exhausted")
            return state
        except NonRetryableError as exc:
            _append_error(state, f"{func.__name__}: {exc}")
            return state
        except Exception as exc:
            logger.warning("agent_node_unexpected_error", node=func.__name__, error=str(exc))
            _append_error(state, f"{func.__name__} unexpected error: {exc}")
            return state

    wrapper.__name__ = func.__name__
    wrapper.__qualname__ = func.__qualname__
    wrapper.__doc__ = func.__doc__
    return wrapper


# ============================================================
# Helpers
# ============================================================


def _append_error(state: AgentState, msg: str) -> None:
    """Append an error message to state['error'] using '; ' separator."""
    prev = state.get("error")
    state["error"] = f"{prev}; {msg}" if prev else msg


def create_initial_state(original_query: str, trace_id: str = "") -> AgentState:
    """Factory for a blank AgentState with sensible defaults."""
    return AgentState(
        original_query=original_query,
        rewritten_query="",
        effective_query="",
        conversation_id="",
        turn_index=0,
        parent_run_id=None,
        recent_turns=[],
        context_summary=None,
        route="tech_general",
        route_confidence=0.0,
        workspace_policy="public_only",
        workspace_ids=[],
        selected_project=None,
        selected_workspace_slug=None,
        display_workspace_slug=None,
        effective_workspace_slugs=[],
        scope_reason_code=None,
        scope_reason_params=None,
        workspace_alias_hits=[],
        key_entities=[],
        retrieved_chunks=[],
        reranked_chunks=[],
        evidence_sufficient=False,
        tools_to_call=[],
        tool_params={},
        tool_results=[],
        latest_tool_results=[],
        tool_loop_count=0,
        working_context_preview=None,
        working_context_diagnostics=None,
        answer="",
        citations=[],
        confidence_score=0.0,
        refused=False,
        refusal_reason=None,
        trace_id=trace_id,
        query_id=trace_id,
        error=None,
    )
