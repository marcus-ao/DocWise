"""tool_executor — execute planned tools with limits and timeout."""
from __future__ import annotations

import asyncio
import time

import structlog
from langchain_core.runnables import RunnableConfig

from src.agent._tracer_stub import write_tool_call, write_trace_event
from src.agent.state import (
    TOOL_MAX_CALLS_PER_RUN,
    TOOL_MAX_CALLS_PER_TOOL,
    AgentState,
    ToolExecutionError,
    _append_error,
)

logger = structlog.get_logger(__name__)

_TOOL_TIMEOUTS: dict[str, float] = {
    "search_docs": 30.0,
    "query_project_manifest": 10.0,
    "query_service_status": 10.0,
    "query_mock_logs": 10.0,
    "generate_runbook_draft": 30.0,
}


def _get_tool_registry() -> dict:
    from src.agent.tools import TOOL_REGISTRY
    return TOOL_REGISTRY


async def tool_executor(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
    start = time.perf_counter()
    tools_to_call = state["tools_to_call"]
    tool_params: dict[str, dict] = state.get("tool_params", {})

    registry = _get_tool_registry()
    total_calls = sum(1 for r in state["tool_results"] if r.get("status"))
    per_tool_counts: dict[str, int] = {}
    for r in state["tool_results"]:
        name = r.get("tool_name", "")
        per_tool_counts[name] = per_tool_counts.get(name, 0) + 1

    new_results: list[dict] = []
    call_index = total_calls

    for tool_name in tools_to_call:
        if total_calls + len(new_results) >= TOOL_MAX_CALLS_PER_RUN:
            break
        if per_tool_counts.get(tool_name, 0) >= TOOL_MAX_CALLS_PER_TOOL:
            continue

        tool_func = registry.get(tool_name)
        if not tool_func:
            tool_latency = 0
            entry = {
                "tool_name": tool_name, "status": "error",
                "output": {}, "error": f"unknown tool: {tool_name}",
            }
            new_results.append(entry)
            await write_tool_call(
                run_id=state["trace_id"], tool_name=tool_name,
                call_index=call_index, input_json={},
                status="error", latency_ms=tool_latency,
                error_message=entry["error"],
            )
            call_index += 1
            continue

        params = tool_params.get(tool_name, {})
        timeout = _TOOL_TIMEOUTS.get(tool_name, 10.0)
        tool_start = time.perf_counter()

        try:
            result = await asyncio.wait_for(tool_func(**params), timeout=timeout)
            tool_latency = int((time.perf_counter() - tool_start) * 1000)
            entry = {
                "tool_name": tool_name, "status": "success",
                "output": result if isinstance(result, dict) else result.model_dump(),
                "error": None,
            }
            new_results.append(entry)
            per_tool_counts[tool_name] = per_tool_counts.get(tool_name, 0) + 1

            await write_tool_call(
                run_id=state["trace_id"], tool_name=tool_name,
                call_index=call_index, input_json=params,
                output_json=entry["output"], status="success",
                latency_ms=tool_latency,
            )
        except TimeoutError:
            tool_latency = int((time.perf_counter() - tool_start) * 1000)
            entry = {
                "tool_name": tool_name, "status": "error",
                "output": {}, "error": f"{tool_name} timeout after {timeout}s",
            }
            new_results.append(entry)
            await write_tool_call(
                run_id=state["trace_id"], tool_name=tool_name,
                call_index=call_index, input_json=params,
                status="error", latency_ms=tool_latency,
                error_message=entry["error"],
            )
        except ToolExecutionError as exc:
            tool_latency = int((time.perf_counter() - tool_start) * 1000)
            entry = {
                "tool_name": tool_name, "status": "error",
                "output": {}, "error": str(exc),
            }
            new_results.append(entry)
            await write_tool_call(
                run_id=state["trace_id"], tool_name=tool_name,
                call_index=call_index, input_json=params,
                status="error", latency_ms=tool_latency,
                error_message=str(exc),
            )
        except Exception as exc:
            tool_latency = int((time.perf_counter() - tool_start) * 1000)
            entry = {
                "tool_name": tool_name, "status": "error",
                "output": {}, "error": str(exc),
            }
            new_results.append(entry)
            await write_tool_call(
                run_id=state["trace_id"], tool_name=tool_name,
                call_index=call_index, input_json=params,
                status="error", latency_ms=tool_latency,
                error_message=str(exc),
            )

        call_index += 1

    state["tool_results"] = state["tool_results"] + new_results
    state["latest_tool_results"] = new_results
    state["tool_loop_count"] = state.get("tool_loop_count", 0) + 1

    failed = [r for r in new_results if r["status"] == "error"]
    if failed and len(failed) == len(new_results):
        _append_error(state, "all tools failed in this round")

    elapsed = int((time.perf_counter() - start) * 1000)
    await write_trace_event(
        run_id=state["trace_id"], node_name="tool_executor", sequence_no=10,
        status="success",
        input_summary={"tools": tools_to_call, "loop_count": state["tool_loop_count"]},
        output_summary={
            "tool_count": len(new_results),
            "success_count": len(new_results) - len(failed),
            "failed_count": len(failed),
        },
        latency_ms=elapsed,
    )
    return state
