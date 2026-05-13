"""query_router — rule-first + LLM JSON classification fallback."""
from __future__ import annotations

import json
import re
import time
from typing import Literal, cast

import structlog
from langchain_core.runnables import RunnableConfig

from src.agent._tracer_stub import write_trace_event
from src.agent.prompts.router import build_router_messages
from src.agent.state import AgentState, NonRetryableError, RetryableError
from src.llm.client import chat_completion

logger = structlog.get_logger(__name__)

_TROUBLESHOOTING_PATTERNS = re.compile(
    r"(error|fail|crash|timeout|exception|异常|失败|超时|报错|挂了|宕机|OOM|502|503|504|500|"
    r"CrashLoopBackOff|SIGKILL|SIGTERM|heartbeat|connection refused|connection timeout)",
    re.IGNORECASE,
)
_PROJECT_PATTERNS = re.compile(
    r"(我们(的|项目)|内部|SLA|负责人|owner|架构图|部署文档|SOP|当前服务|我们的服务)",
    re.IGNORECASE,
)
_RUNBOOK_PATTERNS = re.compile(
    r"(写一个|生成|创建|draft).{0,10}(runbook|SOP|操作手册|应急预案|故障手册)",
    re.IGNORECASE,
)
_OUT_OF_SCOPE_PATTERNS = re.compile(
    r"(股票|彩票|天气预报|星座|算命|绕过权限|破解|hack\b|sql.?inject|注入攻击)",
    re.IGNORECASE,
)

RouteName = Literal["tech_general", "project_specific", "troubleshooting", "runbook_generation", "out_of_scope"]
WorkspacePolicyName = Literal["public_only", "selected_project_plus_public", "none"]

_ROUTE_TO_POLICY: dict[RouteName, WorkspacePolicyName] = {
    "tech_general": "public_only",
    "project_specific": "selected_project_plus_public",
    "troubleshooting": "selected_project_plus_public",
    "runbook_generation": "selected_project_plus_public",
    "out_of_scope": "none",
}

VALID_ROUTES: set[RouteName] = {
    "tech_general",
    "project_specific",
    "troubleshooting",
    "runbook_generation",
    "out_of_scope",
}


def _rule_route(query: str) -> dict | None:
    if _OUT_OF_SCOPE_PATTERNS.search(query):
        return {"route": "out_of_scope", "confidence": 0.95, "key_entities": [], "needs_tools": False}
    if _RUNBOOK_PATTERNS.search(query):
        return {"route": "runbook_generation", "confidence": 0.90, "key_entities": [], "needs_tools": True}
    if _TROUBLESHOOTING_PATTERNS.search(query):
        return {"route": "troubleshooting", "confidence": 0.85, "key_entities": [], "needs_tools": True}
    if _PROJECT_PATTERNS.search(query):
        return {"route": "project_specific", "confidence": 0.80, "key_entities": [], "needs_tools": False}
    return None


async def query_router(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
    start = time.perf_counter()
    query = state["rewritten_query"] or state["original_query"]
    history_used = False

    rule_result = _rule_route(query)
    if rule_result:
        route = rule_result["route"]
        route = cast(RouteName, route)
        state["route"] = route
        state["route_confidence"] = rule_result["confidence"]
        state["workspace_policy"] = _ROUTE_TO_POLICY[route]
        state["key_entities"] = rule_result["key_entities"]
    else:
        try:
            history_used = bool(state.get("recent_turns") or state.get("context_summary"))
            messages = build_router_messages(
                query,
                recent_turns=state.get("recent_turns") or None,
                context_summary=state.get("context_summary"),
            )
            resp = await chat_completion(
                messages, model="fast", temperature=0,
                response_format={"type": "json_object"}, timeout=15.0,
            )
            parsed = json.loads(resp["content"])
            if not isinstance(parsed, dict):
                raise ValueError("router response must be a JSON object")
            route = parsed.get("route", "tech_general")
            if route not in VALID_ROUTES:
                route = "tech_general"
            route = cast(RouteName, route)
            state["route"] = route
            confidence = float(parsed.get("confidence", 0.5))
            state["route_confidence"] = max(0.0, min(1.0, confidence))
            state["workspace_policy"] = _ROUTE_TO_POLICY[route]
            key_entities = parsed.get("key_entities", [])
            state["key_entities"] = key_entities if isinstance(key_entities, list) else []
        except (RetryableError, NonRetryableError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.warning("query_router_llm_fallback", error=str(exc))
            state["route"] = "tech_general"
            state["route_confidence"] = 0.3
            state["workspace_policy"] = "public_only"
            state["key_entities"] = []

    elapsed = int((time.perf_counter() - start) * 1000)
    await write_trace_event(
        run_id=state["trace_id"],
        node_name="query_router",
        sequence_no=3,
        status="success",
        input_summary={"query": query[:200]},
        output_summary={
            "route": state["route"],
            "confidence": state["route_confidence"],
            "workspace_policy": state["workspace_policy"],
        },
        metadata={
            "history_used": history_used,
            "recent_turn_count": len(state.get("recent_turns") or []),
            "context_summary_present": bool(state.get("context_summary")),
        },
        latency_ms=elapsed,
    )
    return state
