"""LangGraph main graph — 12 nodes, conditional branches, tool loop."""
from __future__ import annotations

import time
import uuid

import structlog
from langgraph.graph import END, StateGraph

from src.agent._tracer_stub import complete_agent_run, create_agent_run
from src.agent.nodes import (
    answer_generator,
    citation_verifier,
    context_loader,
    evidence_validator,
    hybrid_retriever,
    input_normalizer,
    query_rewriter,
    query_router,
    refusal_checker,
    reranker_node,
    scope_selector,
    tool_executor,
    tool_planner,
)
from src.agent.state import (
    TOOL_LOOP_MAX_ROUNDS,
    AgentState,
    RetryBudget,
    create_initial_state,
    safe_node,
)

logger = structlog.get_logger(__name__)


# ============================================================
# Conditional routing functions
# ============================================================


def route_after_router(state: AgentState) -> str:
    """out_of_scope → refusal_checker, otherwise → scope_selector."""
    return "out_of_scope" if state["route"] == "out_of_scope" else "continue"


def route_after_evidence(state: AgentState) -> str:
    """Decide next step after evidence validation."""
    if state["route"] == "troubleshooting" and state.get("tool_loop_count", 0) == 0:
        return "need_tools"
    if state["evidence_sufficient"]:
        return "sufficient"
    if (
        state["route"] in ("troubleshooting", "runbook_generation")
        and state.get("tool_loop_count", 0) < TOOL_LOOP_MAX_ROUNDS
    ):
        return "need_tools"
    return "generate_anyway"


def route_after_tools(state: AgentState) -> str:
    """After tool execution: loop back or proceed to generation."""
    if (
        state.get("tool_loop_count", 0) < TOOL_LOOP_MAX_ROUNDS
        and not state.get("evidence_sufficient", False)
    ):
        return "loop"
    return "generate"


# ============================================================
# Graph builder
# ============================================================


def build_agent_graph() -> StateGraph:
    """Build and return the compiled LangGraph agent graph."""
    graph = StateGraph(AgentState)

    graph.add_node("input_normalizer", safe_node(input_normalizer))
    graph.add_node("context_loader", safe_node(context_loader))
    graph.add_node("query_router", safe_node(query_router))
    graph.add_node("scope_selector", safe_node(scope_selector))
    graph.add_node("query_rewriter", safe_node(query_rewriter))
    graph.add_node("hybrid_retriever", safe_node(hybrid_retriever))
    graph.add_node("reranker", safe_node(reranker_node))
    graph.add_node("evidence_validator", safe_node(evidence_validator))
    graph.add_node("tool_planner", safe_node(tool_planner))
    graph.add_node("tool_executor", safe_node(tool_executor))
    graph.add_node("answer_generator", safe_node(answer_generator))
    graph.add_node("citation_verifier", safe_node(citation_verifier))
    graph.add_node("refusal_checker", safe_node(refusal_checker))

    graph.set_entry_point("input_normalizer")
    graph.add_edge("input_normalizer", "context_loader")
    graph.add_edge("context_loader", "query_router")

    graph.add_conditional_edges(
        "query_router",
        route_after_router,
        {"out_of_scope": "refusal_checker", "continue": "scope_selector"},
    )

    graph.add_edge("scope_selector", "query_rewriter")
    graph.add_edge("query_rewriter", "hybrid_retriever")
    graph.add_edge("hybrid_retriever", "reranker")
    graph.add_edge("reranker", "evidence_validator")

    graph.add_conditional_edges(
        "evidence_validator",
        route_after_evidence,
        {
            "sufficient": "answer_generator",
            "need_tools": "tool_planner",
            "generate_anyway": "answer_generator",
        },
    )

    graph.add_edge("tool_planner", "tool_executor")

    graph.add_conditional_edges(
        "tool_executor",
        route_after_tools,
        {"loop": "evidence_validator", "generate": "answer_generator"},
    )

    graph.add_edge("answer_generator", "citation_verifier")
    graph.add_edge("citation_verifier", "refusal_checker")
    graph.add_edge("refusal_checker", END)

    return graph.compile()


# ============================================================
# Run helper
# ============================================================


async def run_agent(
    original_query: str,
    query_id: str | None = None,
    workspace_slug: str | None = None,
) -> AgentState:
    """Execute the full agent pipeline and return final state."""
    start = time.perf_counter()

    qid = query_id or str(uuid.uuid4())
    run_id = await create_agent_run(
        query_id=qid,
        original_query=original_query,
        workspace_slug=workspace_slug,
    )

    state = create_initial_state(original_query=original_query, trace_id=run_id)
    state["query_id"] = qid
    state["conversation_id"] = qid
    if workspace_slug:
        state["selected_workspace_slug"] = workspace_slug
    budget = RetryBudget(max_total_retries=3)
    config = {"configurable": {"retry_budget": budget}}

    compiled = build_agent_graph()
    final_state = await compiled.ainvoke(state, config=config)

    latency_ms = int((time.perf_counter() - start) * 1000)

    status = "refused" if final_state.get("refused") else "succeeded"
    if final_state.get("error") and not final_state.get("answer"):
        status = "failed"

    await complete_agent_run(
        run_id=run_id,
        status=status,
        answer=final_state.get("answer"),
        citations=final_state.get("citations"),
        route=final_state.get("route"),
        route_confidence=final_state.get("route_confidence"),
        workspace_policy=final_state.get("workspace_policy"),
        workspace_ids=final_state.get("workspace_ids"),
        confidence_score=final_state.get("confidence_score"),
        refused=final_state.get("refused", False),
        refusal_reason=final_state.get("refusal_reason"),
        latency_ms=latency_ms,
        error_message=final_state.get("error"),
        display_workspace_slug=final_state.get("display_workspace_slug"),
    )

    return final_state
