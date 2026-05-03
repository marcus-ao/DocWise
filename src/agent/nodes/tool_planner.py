"""tool_planner — fixed tool chains + LLM parameter completion."""
from __future__ import annotations

import json
import re
import time

import structlog
from langchain_core.runnables import RunnableConfig

from src.agent._tracer_stub import write_trace_event
from src.agent.prompts.tool_planner import build_tool_planner_messages
from src.agent.state import AgentState, NonRetryableError, RetryableError
from src.llm.client import chat_completion

logger = structlog.get_logger(__name__)

_ROUTE_TOOL_CHAINS: dict[str, list[str]] = {
    "troubleshooting": ["query_project_manifest", "query_service_status", "query_mock_logs"],
    "runbook_generation": ["search_docs", "query_project_manifest", "generate_runbook_draft"],
    "project_specific": ["query_project_manifest"],
}


async def tool_planner(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
    start = time.perf_counter()
    route = state["route"]
    query = state["rewritten_query"] or state["original_query"]

    tools = list(_ROUTE_TOOL_CHAINS.get(route, []))
    state["tools_to_call"] = tools

    tool_params: dict[str, dict] = {}
    if tools:
        try:
            messages = build_tool_planner_messages(
                query, state["key_entities"], state["selected_project"], tools,
            )
            resp = await chat_completion(
                messages, model="fast", temperature=0,
                response_format={"type": "json_object"}, timeout=15.0,
            )
            parsed = json.loads(resp["content"])
            tool_params = parsed.get("tool_params", {})
        except (RetryableError, NonRetryableError, json.JSONDecodeError) as exc:
            logger.warning("tool_planner_llm_failed", error=str(exc))
            tool_params = _default_params(state)

    if not tool_params:
        tool_params = _default_params(state)
    tool_params = _normalize_tool_params(state, tools, tool_params)

    state["tool_params"] = tool_params

    elapsed = int((time.perf_counter() - start) * 1000)
    await write_trace_event(
        run_id=state["trace_id"], node_name="tool_planner", sequence_no=8,
        status="success",
        input_summary={"route": route, "query": query[:200]},
        output_summary={"selected_tools": tools, "tool_params": tool_params},
        latency_ms=elapsed,
    )
    return state


def _default_params(state: AgentState) -> dict[str, dict]:
    project = state.get("selected_project")
    service_name = _derive_service_name(state)

    params: dict[str, dict] = {}
    if project or service_name:
        params["query_project_manifest"] = {}
        if project:
            params["query_project_manifest"]["project_name"] = project
        if service_name:
            params["query_project_manifest"]["service_name"] = service_name
    if service_name:
        params["query_service_status"] = {"service_name": service_name}
        params["query_mock_logs"] = {
            "service_name": service_name,
            "time_range": "last_30m",
            "level": "ERROR",
            "keywords": [],
        }
    return params


def _normalize_tool_params(state: AgentState, tools: list[str], tool_params: dict) -> dict[str, dict]:
    defaults = _default_params(state)
    cleaned: dict[str, dict] = {}

    for tool in tools:
        params = tool_params.get(tool, {})
        params = params if isinstance(params, dict) else {}
        merged = {**defaults.get(tool, {}), **_drop_blank_values(params)}
        if merged:
            cleaned[tool] = merged

    service_name = _extract_service_name(cleaned) or _derive_service_name(state)
    if service_name:
        for tool in ("query_service_status", "query_mock_logs"):
            if tool in tools:
                cleaned.setdefault(tool, {})
                cleaned[tool].setdefault("service_name", service_name)
        if "query_project_manifest" in tools:
            cleaned.setdefault("query_project_manifest", {})
            cleaned["query_project_manifest"].setdefault("service_name", service_name)

    if "query_mock_logs" in cleaned:
        cleaned["query_mock_logs"].setdefault("time_range", "last_30m")
        cleaned["query_mock_logs"].setdefault("level", "ERROR")
        cleaned["query_mock_logs"].setdefault("keywords", [])

    return cleaned


def _drop_blank_values(params: dict) -> dict:
    return {
        key: value
        for key, value in params.items()
        if value is not None and not (isinstance(value, str) and not value.strip())
    }


def _extract_service_name(tool_params: dict[str, dict]) -> str | None:
    for params in tool_params.values():
        service_name = params.get("service_name")
        if isinstance(service_name, str) and service_name.strip():
            return service_name.strip()
    return None


def _derive_service_name(state: AgentState) -> str | None:
    text_parts = [
        state.get("original_query", ""),
        state.get("rewritten_query", ""),
        state.get("selected_project") or "",
        state.get("selected_workspace_name") or "",
        " ".join(str(entity) for entity in state.get("key_entities", [])),
    ]
    text = _normalize_text(" ".join(text_parts))
    aliases = [
        ("airflow", "airflow"),
        ("data-platform", "airflow"),
        ("project-airflow", "airflow"),
        ("backstage", "backstage"),
        ("backstage-portal", "backstage"),
        ("fastapi", "fastapi"),
        ("api-gateway", "fastapi"),
    ]
    for needle, service_name in aliases:
        if needle in text:
            return service_name

    for entity in state.get("key_entities", []):
        value = str(entity).strip()
        if value:
            return value
    return None


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower().replace("_", "-"))
