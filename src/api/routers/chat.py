"""Chat API routes, including LangGraph-to-SSE streaming."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Protocol, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from openai import RateLimitError
from sqlalchemy import delete, exists, func, select

from src.agent.conversation import CANCELLED_RUN_MARKER, prepare_stream_conversation_run
from src.agent.graph import build_agent_graph, run_agent
from src.agent.state import RetryableError, RetryBudget, create_initial_state
from src.api.citations import citation_from_dict, citations_from_final, citations_from_retrieval_rows
from src.api.deps import DbSession
from src.models.agent import AgentRun, ToolCall, TraceEvent
from src.models.feedback import Feedback
from src.models.query import Query, RetrievalResult
from src.models.workspace import Workspace
from src.observability import complete_agent_run, update_agent_run_progress
from src.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ConversationArchiveRequest,
    ConversationMutationResponse,
    ConversationRenameRequest,
    FeedbackRequest,
    FeedbackResponse,
)
from src.schemas.frontend import (
    ChatConversationDetail,
    ChatConversationListItem,
    ChatConversationListResponse,
    ChatConversationMessage,
)
from src.schemas.shared import ToolCallItem, TraceEventItem

router = APIRouter(prefix="/chat", tags=["chat"])
HEARTBEAT_INTERVAL_SECONDS = 30.0
RUN_CANCEL_EVENTS: dict[str, asyncio.Event] = {}


class EventStreamGraph(Protocol):
    def astream_events(self, input: dict, **kwargs: object) -> AsyncIterator[dict]: ...


def _value(value: object, default: object = None) -> object:
    return default if value is None else value


def _json_default(value: object) -> str:
    return str(value)


def format_sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False, default=_json_default)}\n\n"


async def _persist_partial_completion(
    *,
    run_id: str,
    final_state: dict,
    partial_answer: str,
    start_time: float,
    cancelled: bool = False,
) -> None:
    answer = partial_answer or str(final_state.get("answer") or "")
    await complete_agent_run(
        run_id=str(final_state.get("trace_id") or run_id),
        status="refused" if final_state.get("refused") else "succeeded",
        answer=answer,
        citations=final_state.get("citations"),
        route=final_state.get("route"),
        route_confidence=final_state.get("route_confidence"),
        workspace_policy=final_state.get("workspace_policy"),
        workspace_ids=final_state.get("workspace_ids"),
        confidence_score=final_state.get("confidence_score"),
        refused=bool(final_state.get("refused", False)),
        refusal_reason=final_state.get("refusal_reason"),
        latency_ms=int((time.perf_counter() - start_time) * 1000),
        error_message=CANCELLED_RUN_MARKER if cancelled else final_state.get("error"),
        display_workspace_slug=final_state.get("display_workspace_slug"),
    )


def _state_from_event(event: dict) -> dict:
    data = event.get("data") or {}
    output = data.get("output")
    if isinstance(output, dict):
        return output
    input_state = data.get("input")
    if isinstance(input_state, dict):
        return input_state
    return data if isinstance(data, dict) else {}


def _latest_tool_results(state: dict) -> list[dict]:
    tool_results = list(state.get("tool_results") or [])
    tools_to_call = list(state.get("tools_to_call") or [])
    if not tool_results or not tools_to_call:
        return tool_results
    return tool_results[-len(tools_to_call) :]


def _tool_summary(result: dict) -> str:
    if result.get("error"):
        return str(result["error"])
    output = result.get("output")
    if isinstance(output, dict):
        summary = output.get("summary") or output.get("message") or output.get("status")
        if summary is not None:
            return str(summary)
    return "Tool completed"


def _error_type(error: Exception) -> str:
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, RateLimitError):
        return "rate_limit"
    if isinstance(error, RetryableError):
        message = str(error).lower()
        if "timeout" in message:
            return "timeout"
        if "rate" in message or "429" in message:
            return "rate_limit"
        return "llm_error"
    return "internal_error"


def _token_content(event: dict) -> str:
    chunk = (event.get("data") or {}).get("chunk")
    content = getattr(chunk, "content", None)
    if content is None and isinstance(chunk, dict):
        content = chunk.get("content")
    if isinstance(content, list):
        return "".join(str(part) for part in content)
    return str(content or "")


def _conversation_title(query: str) -> str:
    normalized = " ".join(query.split())
    if len(normalized) <= 48:
        return normalized or "未命名对话"
    return f"{normalized[:45]}..."


def _stored_conversation_title(query: Query) -> str:
    return getattr(query, "conversation_title", None) or _conversation_title(query.original_query)


def _reasoning_title(node_name: str) -> str:
    return {
        "context_loader": "上下文装配",
        "scope_selector": "知识域范围",
        "query_router": "路由决策",
        "hybrid_retriever": "混合检索",
        "reranker": "结果重排",
        "evidence_validator": "证据校验",
        "tool_planner": "工具规划",
        "tool_executor": "工具执行",
        "citation_verifier": "引用校验",
        "answer_generator": "答案生成",
    }.get(node_name, node_name)


def _reasoning_payload(event: dict) -> dict | None:
    event_type = event.get("event")
    node_name = str(event.get("name") or "")
    if event_type not in {"on_chain_start", "on_chain_end", "on_chain_error"} or not node_name:
        return None

    state = _state_from_event(event)
    status_value = "active" if event_type == "on_chain_start" else "complete"
    if event_type == "on_chain_error" or state.get("error"):
        status_value = "error"

    payload: dict[str, object] = {
        "node": node_name,
        "title": _reasoning_title(node_name),
        "status": status_value,
    }
    if node_name == "query_router":
        payload.update(
            {
                "decision": state.get("route"),
                "reason": f"工作区策略: {state.get('workspace_policy', 'public_only')}",
                "confidence": float(state.get("route_confidence") or 0.0),
            }
        )
    elif node_name == "scope_selector":
        payload.update(
            {
                "reason": str(state.get("scope_reason_code") or "scope_resolved"),
                "workspace_policy": state.get("workspace_policy"),
                "workspace_ids": list(state.get("workspace_ids") or []),
                "effective_workspace_slugs": list(state.get("effective_workspace_slugs") or []),
                "selected_project": state.get("selected_project"),
                "scope_reason_code": state.get("scope_reason_code"),
                "scope_reason_params": state.get("scope_reason_params"),
            }
        )
    elif node_name == "context_loader":
        turns = list(state.get("recent_turns") or [])
        payload["reason"] = f"加载 {len(turns)} 轮历史上下文"
    elif node_name == "hybrid_retriever":
        payload.update(
            {
                "reason": f"召回 {len(state.get('retrieved_chunks') or [])} 个候选片段",
                "workspace_ids": list(state.get("workspace_ids") or []),
            }
        )
    elif node_name == "reranker":
        payload["reason"] = f"保留 {len(state.get('reranked_chunks') or [])} 个高相关片段"
    elif node_name == "tool_executor":
        tools = list(state.get("tools_to_call") or [])
        payload["reason"] = "、".join(str(tool) for tool in tools) if tools else "工具执行完成"
    elif node_name == "citation_verifier":
        payload["reason"] = f"验证 {len(state.get('citations') or [])} 条引用"
    elif node_name == "answer_generator":
        payload.update(
            {
                "reason": "生成最终回答",
                "confidence": float(state.get("confidence_score") or 0.0),
            }
        )
    else:
        payload["reason"] = str(state.get("error") or "节点执行中")
    return payload


async def map_langgraph_event_to_reasoning_sse(event: dict) -> str | None:
    payload = _reasoning_payload(event)
    return format_sse("reasoning", payload) if payload else None


async def map_langgraph_event_to_sse(event: dict) -> str | None:
    event_type = event.get("event")
    name = event.get("name")
    state = _state_from_event(event)

    if event_type == "on_chain_end" and name == "query_router" and state.get("route") == "out_of_scope":
        return format_sse(
            "route",
            {
                "route": str(state.get("route", "tech_general")),
                "confidence": float(state.get("route_confidence") or 0.0),
                "workspace_policy": str(state.get("workspace_policy", "public_only")),
                "workspace_ids": list(state.get("workspace_ids") or []),
                "selected_project": state.get("selected_project"),
                "effective_workspace_slugs": [],
                "scope_reason_code": "out_of_scope",
                "scope_reason_params": {"route": "out_of_scope"},
            },
        )
    if event_type == "on_chain_end" and name == "scope_selector":
        return format_sse(
            "route",
            {
                "route": str(state.get("route", "tech_general")),
                "confidence": float(state.get("route_confidence") or 0.0),
                "workspace_policy": str(state.get("workspace_policy", "public_only")),
                "workspace_ids": list(state.get("workspace_ids") or []),
                "selected_project": state.get("selected_project"),
                "effective_workspace_slugs": list(state.get("effective_workspace_slugs") or []),
                "scope_reason_code": state.get("scope_reason_code"),
                "scope_reason_params": state.get("scope_reason_params"),
            },
        )
    if event_type == "on_chain_end" and name == "hybrid_retriever":
        return format_sse(
            "retrieval",
            {
                "chunk_count": len(state.get("retrieved_chunks") or []),
                "workspace_ids": list(state.get("workspace_ids") or []),
            },
        )
    if event_type == "on_chain_end" and name == "reranker":
        return format_sse(
            "rerank",
            {
                "top_k": len(state.get("reranked_chunks") or []),
                "fallback": bool(state.get("error") and "rerank" in str(state.get("error")).lower()),
            },
        )
    if event_type == "on_chain_start" and name == "tool_executor":
        return format_sse(
            "tool_call",
            {"tools": list(state.get("tools_to_call") or []), "loop_round": int(state.get("tool_loop_count") or 0) + 1},
        )
    if event_type == "on_chain_end" and name == "tool_executor":
        latest_results = _latest_tool_results(state)
        return format_sse(
            "tool_result",
            {
                "results": [
                    {
                        "tool": str(item.get("tool_name") or item.get("tool") or "unknown"),
                        "status": str(item.get("status") or "success"),
                        "summary": _tool_summary(item),
                    }
                    for item in latest_results
                ]
            },
        )
    if event_type == "on_chat_model_stream" and name == "answer_generator":
        return format_sse("token", {"content": _token_content(event)})
    if event_type == "on_chain_end" and name == "answer_generator":
        answer = str(state.get("answer") or "")
        if answer:
            return format_sse(
                "answer",
                {
                    "content": answer,
                    "confidence_score": float(state.get("confidence_score") or 0.0),
                },
            )
    if event_type == "on_chain_end" and name == "citation_verifier":
        citations = []
        for index, item in enumerate(state.get("citations") or [], start=1):
            citations.append(
                {
                    "index": int(item.get("index") or index),
                    "chunk_uid": str(item.get("chunk_uid") or ""),
                    "document_title": str(item.get("document_title") or ""),
                    "section_path": item.get("section_path"),
                    "page_number": item.get("page_number"),
                    "score": float(item.get("score") or item.get("rerank_score") or 0.0),
                    "quote": str(item.get("quote") or ""),
                }
            )
        return format_sse("citation", {"citations": citations})
    return None


async def _events_with_heartbeat(
    graph: EventStreamGraph,
    state: dict,
    cancel_event: asyncio.Event | None = None,
) -> AsyncIterator[tuple[str, object | None]]:
    queue: asyncio.Queue[tuple[str, object | None]] = asyncio.Queue()

    async def token_sink(token: str) -> None:
        await queue.put(("token", token))

    async def producer() -> None:
        try:
            async for event in graph.astream_events(
                dict(state),
                version="v2",
                config={"configurable": {"retry_budget": RetryBudget(max_total_retries=3), "token_sink": token_sink}},
            ):
                if cancel_event is not None and cancel_event.is_set():
                    await queue.put(("cancelled", None))
                    return
                await queue.put(("graph", event))
        except Exception as exc:  # noqa: BLE001 - forwarded into SSE contract.
            await queue.put(("error", exc))
        finally:
            await queue.put(("done", None))

    producer_task = asyncio.create_task(producer())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_INTERVAL_SECONDS)
            except TimeoutError:
                if cancel_event is not None and cancel_event.is_set():
                    yield ("cancelled", None)
                    return
                yield ("heartbeat", None)
                continue
            yield item
            if item[0] == "done":
                return
    finally:
        if not producer_task.done():
            producer_task.cancel()
            with suppress(asyncio.CancelledError):
                await producer_task


async def _tool_calls_for_run(db: DbSession, run_id: UUID) -> list[ToolCallItem]:
    rows = (await db.scalars(select(ToolCall).where(ToolCall.run_id == run_id).order_by(ToolCall.call_index))).all()
    return [
        ToolCallItem(
            tool_name=row.tool_name,
            call_index=row.call_index,
            input_json=row.input_json,
            output_json=row.output_json,
            status=str(getattr(row.status, "value", row.status)),
            latency_ms=row.latency_ms,
            error_message=row.error_message,
        )
        for row in rows
    ]


async def _load_conversation_runs(db: DbSession, query_id: UUID) -> list[AgentRun]:
    rows = (
        await db.scalars(
            select(AgentRun)
            .where(AgentRun.query_id == query_id)
            .order_by(AgentRun.turn_index.asc().nullslast(), AgentRun.created_at.asc(), AgentRun.id.asc())
        )
    ).all()
    return list(rows)


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest, db: DbSession) -> ChatResponse:
    start = time.perf_counter()
    query_id = uuid4()
    final_state = await run_agent(request.query, query_id=str(query_id), workspace_slug=request.workspace_slug)
    run_id = UUID(str(final_state.get("trace_id") or uuid4()))
    tool_calls = await _tool_calls_for_run(db, run_id)
    return ChatResponse(
        query_id=query_id,
        run_id=run_id,
        route=str(final_state.get("route", "tech_general")),
        route_confidence=float(final_state.get("route_confidence") or 0.0),
        workspace_ids=[str(item) for item in final_state.get("workspace_ids") or []],
        answer=str(final_state.get("answer") or ""),
        citations=[citation_from_dict(item) for item in final_state.get("citations") or []],
        confidence_score=float(final_state.get("confidence_score") or 0.0),
        refused=bool(final_state.get("refused", False)),
        refusal_reason=final_state.get("refusal_reason"),
        latency_ms=int((time.perf_counter() - start) * 1000),
        tool_calls=tool_calls,
    )


@router.post("/stream")
async def chat_stream(request: ChatRequest, db: DbSession) -> StreamingResponse:
    async def event_generator() -> AsyncIterator[str]:
        start = time.perf_counter()
        conversation_id = str(request.conversation_id or uuid4())
        query_id = conversation_id
        run_id = str(uuid4())
        partial_answer = ""
        last_progress_persist_len = 0
        has_persisted_first_progress = False
        state = create_initial_state(original_query=request.query, trace_id=run_id)
        state["query_id"] = query_id
        state["conversation_id"] = conversation_id
        if request.workspace_slug:
            state["selected_workspace_slug"] = request.workspace_slug
        final_state: dict = dict(state)
        out_of_scope = False
        cancel_event = asyncio.Event()
        try:
            prepared = await prepare_stream_conversation_run(
                db,
                conversation_id=request.conversation_id,
                original_query=request.query,
                workspace_slug=request.workspace_slug,
            )
            query_id = str(prepared.conversation_id)
            conversation_id = query_id
            run_id = prepared.run_id
            RUN_CANCEL_EVENTS[run_id] = cancel_event
            state["trace_id"] = run_id
            state["query_id"] = query_id
            state["conversation_id"] = conversation_id
            state["turn_index"] = prepared.turn_index
            state["parent_run_id"] = str(prepared.parent_run_id) if prepared.parent_run_id else None
            final_state["trace_id"] = run_id
            final_state["query_id"] = query_id
            final_state["conversation_id"] = conversation_id
            final_state["turn_index"] = prepared.turn_index
            final_state["parent_run_id"] = state["parent_run_id"]
            yield format_sse(
                "run",
                {
                    "query_id": query_id,
                    "conversation_id": conversation_id,
                    "run_id": run_id,
                    "turn_index": prepared.turn_index,
                    "parent_run_id": state["parent_run_id"],
                },
            )
            graph = cast(EventStreamGraph, build_agent_graph())
            async for item_type, payload in _events_with_heartbeat(graph, dict(state), cancel_event=cancel_event):
                if item_type == "heartbeat":
                    yield format_sse("token", {"content": ""})
                    continue
                if item_type == "cancelled":
                    final_state["answer"] = partial_answer
                    await _persist_partial_completion(
                        run_id=run_id,
                        final_state=final_state,
                        partial_answer=partial_answer,
                        start_time=start,
                        cancelled=True,
                    )
                    yield format_sse(
                        "cancelled",
                        {
                            "query_id": query_id,
                            "conversation_id": conversation_id,
                            "run_id": str(final_state.get("trace_id") or run_id),
                            "answer": partial_answer,
                            "latency_ms": int((time.perf_counter() - start) * 1000),
                        },
                    )
                    return
                if item_type == "token":
                    token_text = str(payload or "")
                    partial_answer += token_text
                    if partial_answer and not has_persisted_first_progress:
                        await update_agent_run_progress(run_id, answer=partial_answer)
                        last_progress_persist_len = len(partial_answer)
                        has_persisted_first_progress = True
                    elif len(partial_answer) - last_progress_persist_len >= 16:
                        await update_agent_run_progress(run_id, answer=partial_answer)
                        last_progress_persist_len = len(partial_answer)
                    yield format_sse("token", {"content": token_text})
                    continue
                if item_type == "error":
                    raise cast(Exception, payload)
                if item_type == "done":
                    break
                event = cast(dict, payload)
                if event.get("event") == "heartbeat":
                    yield format_sse("token", {"content": ""})
                    continue
                event_state = _state_from_event(event)
                if event_state:
                    final_state = event_state
                    out_of_scope = out_of_scope or final_state.get("route") == "out_of_scope"
                reasoning = await map_langgraph_event_to_reasoning_sse(event)
                mapped = await map_langgraph_event_to_sse(event)
                if reasoning and not out_of_scope:
                    yield reasoning
                if mapped:
                    if out_of_scope and not mapped.startswith("event: route\n"):
                        continue
                    if mapped.startswith("event: answer\n") and partial_answer:
                        continue
                    yield mapped
        except asyncio.CancelledError:
            final_state["answer"] = partial_answer
            await _persist_partial_completion(
                run_id=run_id,
                final_state=final_state,
                partial_answer=partial_answer,
                start_time=start,
            )
            return
        except Exception as error:
            await complete_agent_run(
                run_id=run_id,
                status="failed",
                answer=None,
                error_message=str(error)[:500],
                display_workspace_slug=final_state.get("display_workspace_slug"),
            )
            yield format_sse(
                "error",
                {"error_type": _error_type(error), "message": str(error), "run_id": run_id, "node_name": None},
            )
            return
        finally:
            RUN_CANCEL_EVENTS.pop(run_id, None)

        await _persist_partial_completion(
            run_id=run_id,
            final_state=final_state,
            partial_answer=partial_answer,
            start_time=start,
        )

        yield format_sse(
            "done",
            {
                "query_id": query_id,
                "run_id": str(final_state.get("trace_id") or run_id),
                "conversation_id": conversation_id,
                "refused": bool(final_state.get("refused", False)),
                "refusal_reason": final_state.get("refusal_reason"),
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "answer": partial_answer or str(final_state.get("answer") or ""),
            },
        )

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/runs/{run_id}/cancel", response_model=ConversationMutationResponse, status_code=status.HTTP_202_ACCEPTED)
async def cancel_chat_run(db: DbSession, run_id: UUID) -> ConversationMutationResponse:
    run = await db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    cancel_event = RUN_CANCEL_EVENTS.get(str(run_id))
    if cancel_event is not None:
        cancel_event.set()
    return ConversationMutationResponse(query_id=run.query_id, status="accepted")


@router.get("/conversations", response_model=ChatConversationListResponse)
async def list_conversations(
    db: DbSession,
    workspace_slug: str | None = None,
    archived: bool | None = None,
    limit: int = 20,
    offset: int = 0,
) -> ChatConversationListResponse:
    stmt = select(Query, Workspace).join(Workspace, Workspace.slug == Query.workspace_slug, isouter=True)
    count_stmt = select(func.count()).select_from(Query)
    if workspace_slug:
        stmt = stmt.where(Query.workspace_slug == workspace_slug)
        count_stmt = count_stmt.where(Query.workspace_slug == workspace_slug)
    if archived is not None:
        stmt = stmt.where(Query.is_archived.is_(archived))
        count_stmt = count_stmt.where(Query.is_archived.is_(archived))
    run_activity = (
        select(func.max(func.coalesce(AgentRun.ended_at, AgentRun.created_at)))
        .where(AgentRun.query_id == Query.id)
        .scalar_subquery()
    )
    rows = (
        await db.execute(
            stmt.order_by(func.coalesce(run_activity, Query.created_at).desc(), Query.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    total = int(await db.scalar(count_stmt) or 0)

    items: list[ChatConversationListItem] = []
    for query, workspace in rows:
        runs = await _load_conversation_runs(db, query.id)
        run = runs[-1] if runs else None
        updated_at = (run.ended_at or run.created_at) if run else query.created_at
        items.append(
            ChatConversationListItem(
                id=query.id,
                query_id=query.id,
                run_id=run.id if run else None,
                title=_stored_conversation_title(query),
                is_archived=bool(getattr(query, "is_archived", False)),
                workspace_id=str(workspace.id) if workspace else None,
                workspace_slug=query.workspace_slug,
                created_at=query.created_at,
                updated_at=updated_at,
                message_count=len(runs),
                route=str(getattr(run.route, "value", run.route)) if run and run.route else None,
                status=str(getattr(run.status, "value", run.status)) if run else None,
            )
        )

    return ChatConversationListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/conversations/{conversation_id}", response_model=ChatConversationDetail)
async def get_conversation(db: DbSession, conversation_id: UUID) -> ChatConversationDetail:
    query = await db.get(Query, conversation_id)
    if query is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    workspace = None
    if query.workspace_slug:
        workspace = await db.scalar(select(Workspace).where(Workspace.slug == query.workspace_slug))
    runs = await _load_conversation_runs(db, query.id)
    if not runs:
        maybe_run = await db.scalar(
            select(AgentRun).where(AgentRun.query_id == query.id).order_by(AgentRun.created_at.desc()).limit(1)
        )
        if maybe_run is not None:
            runs = [maybe_run]
    latest_run = runs[-1] if runs else None
    retrieval_rows = (
        await db.scalars(
            select(RetrievalResult)
            .where(RetrievalResult.query_id == query.id)
            .order_by(RetrievalResult.created_at.asc(), RetrievalResult.final_rank.asc())
        )
    ).all()
    rows_by_run: dict[UUID, list[RetrievalResult]] = {}
    for row in retrieval_rows:
        rows_by_run.setdefault(row.run_id, []).append(row)

    messages: list[ChatConversationMessage] = []
    seed_query = query.original_query
    if runs:
        first_run = runs[0]
        first_run_query = str(getattr(first_run, "original_query", seed_query) or seed_query)
        if first_run_query == seed_query:
            messages.append(
                ChatConversationMessage(
                    id=f"{query.id}:user:seed",
                    role="user",
                    content=seed_query,
                    created_at=query.created_at,
                )
            )
        for index, run in enumerate(runs):
            run_query = str(getattr(run, "original_query", seed_query) or seed_query)
            if index > 0 or run_query != seed_query:
                messages.append(
                    ChatConversationMessage(
                        id=f"{run.id}:user",
                        role="user",
                        content=run_query,
                        created_at=run.created_at,
                    )
                )
            citations = citations_from_final(run.final_citations) or citations_from_retrieval_rows(
                rows_by_run.get(run.id, [])
            )
            answer = str(run.answer or "")
            if answer:
                messages.append(
                    ChatConversationMessage(
                        id=f"{run.id}:assistant",
                        role="assistant",
                        content=answer,
                        citations=citations,
                        created_at=(run.ended_at or run.created_at),
                    )
                )
    else:
        messages.append(
            ChatConversationMessage(
                id=f"{query.id}:user",
                role="user",
                content=seed_query,
                created_at=query.created_at,
            )
        )
        if query.answer:
            messages.append(
                ChatConversationMessage(
                    id=f"{query.id}:assistant",
                    role="assistant",
                    content=str(query.answer),
                    citations=[],
                    created_at=query.created_at,
                )
            )

    trace_events: list[TraceEventItem] = []
    if latest_run is not None:
        latest_trace_rows = (
            await db.scalars(
                select(TraceEvent).where(TraceEvent.run_id == latest_run.id).order_by(TraceEvent.sequence_no.asc())
            )
        ).all()
        trace_events = [
            TraceEventItem(
                node_name=row.node_name,
                sequence_no=row.sequence_no,
                status=str(getattr(row.status, "value", row.status)),
                latency_ms=row.latency_ms,
                input_summary=row.input_summary,
                output_summary=row.output_summary,
                error_message=row.error_message,
            )
            for row in latest_trace_rows
        ]

    updated_at = (latest_run.ended_at or latest_run.created_at) if latest_run else query.created_at
    return ChatConversationDetail(
        id=query.id,
        query_id=query.id,
        run_id=latest_run.id if latest_run else None,
        title=_stored_conversation_title(query),
        is_archived=bool(getattr(query, "is_archived", False)),
        workspace_id=str(workspace.id) if workspace else None,
        workspace_slug=query.workspace_slug,
        created_at=query.created_at,
        updated_at=updated_at,
        status=str(getattr(getattr(latest_run, "status", None), "value", getattr(latest_run, "status", None)))
        if latest_run
        else None,
        messages=messages,
        trace_events=trace_events,
    )


@router.get("/history")
async def list_chat_history(
    db: DbSession,
    workspace_slug: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, object]:
    latest_run = (
        select(AgentRun.id)
        .where(AgentRun.query_id == Query.id)
        .order_by(AgentRun.created_at.desc())
        .limit(1)
        .scalar_subquery()
    )
    stmt = (
        select(Query, AgentRun)
        .join(AgentRun, AgentRun.id == latest_run, isouter=True)
    )
    count_stmt = select(func.count()).select_from(Query)
    if workspace_slug:
        stmt = stmt.where(Query.workspace_slug == workspace_slug)
        count_stmt = count_stmt.where(Query.workspace_slug == workspace_slug)
    rows = (await db.execute(stmt.order_by(Query.created_at.desc()).limit(limit).offset(offset))).all()
    total = int(await db.scalar(count_stmt) or 0)
    return {
        "items": [
            {
                "query_id": str(query.id),
                "run_id": str(run.id) if run else None,
                "query": query.original_query,
                "workspace_slug": query.workspace_slug,
                "route": str(getattr(query.route, "value", query.route)) if query.route else None,
                "answer_preview": (query.answer or "")[:160],
                "created_at": query.created_at.isoformat(),
            }
            for query, run in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{query_id}", response_model=ChatResponse)
async def get_chat_history(db: DbSession, query_id: UUID) -> ChatResponse:
    query = await db.get(Query, query_id)
    if query is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Query not found")
    run = await db.scalar(
        select(AgentRun).where(AgentRun.query_id == query_id).order_by(AgentRun.created_at.desc()).limit(1)
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")
    retrieval_rows = (
        await db.scalars(
            select(RetrievalResult)
            .where(RetrievalResult.query_id == query_id)
            .order_by(RetrievalResult.final_rank, RetrievalResult.created_at)
        )
    ).all()
    citations = citations_from_final(run.final_citations) or citations_from_retrieval_rows(list(retrieval_rows))
    return ChatResponse(
        query_id=query.id,
        run_id=run.id,
        route=str(getattr(run.route, "value", run.route or query.route or "tech_general")),
        route_confidence=float(run.route_confidence or query.route_confidence or 0.0),
        workspace_ids=[str(item) for item in run.workspace_ids or []],
        answer=str(run.answer or query.answer or ""),
        citations=citations,
        confidence_score=float(run.confidence_score or query.confidence_score or 0.0),
        refused=bool(run.refused or query.refused),
        refusal_reason=run.refusal_reason or query.refusal_reason,
        latency_ms=int(run.latency_ms or 0),
        tool_calls=await _tool_calls_for_run(db, run.id),
    )


@router.post("/{query_id}/feedback", response_model=FeedbackResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_feedback(db: DbSession, query_id: UUID, request: FeedbackRequest) -> FeedbackResponse:
    query_exists = await db.scalar(select(exists().where(Query.id == query_id)))
    if not query_exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Query not found")
    if request.thumbs not in {None, "up", "down"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="thumbs must be up or down")
    if request.rating is not None and not 1 <= request.rating <= 5:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="rating must be 1-5")
    feedback = Feedback(
        query_id=query_id,
        thumbs=request.thumbs,
        rating=request.rating,
        correction=request.correction,
        comment=request.comment,
    )
    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)
    return FeedbackResponse(id=feedback.id, query_id=query_id, status="accepted")


@router.patch(
    "/conversations/{query_id}/rename",
    response_model=ConversationMutationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def rename_conversation(
    db: DbSession,
    query_id: UUID,
    request: ConversationRenameRequest,
) -> ConversationMutationResponse:
    query = await db.get(Query, query_id)
    if query is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    normalized_title = " ".join(request.title.split())
    if not normalized_title:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="title must not be empty")
    query.conversation_title = normalized_title[:256]
    await db.commit()
    return ConversationMutationResponse(query_id=query_id, status="accepted")


@router.patch(
    "/conversations/{query_id}/archive",
    response_model=ConversationMutationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def archive_conversation(
    db: DbSession,
    query_id: UUID,
    request: ConversationArchiveRequest,
) -> ConversationMutationResponse:
    query = await db.get(Query, query_id)
    if query is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    query.is_archived = request.archived
    await db.commit()
    return ConversationMutationResponse(query_id=query_id, status="accepted")


@router.delete(
    "/conversations/{query_id}",
    response_model=ConversationMutationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def delete_conversation(db: DbSession, query_id: UUID) -> ConversationMutationResponse:
    query = await db.get(Query, query_id)
    if query is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    run_ids = (await db.scalars(select(AgentRun.id).where(AgentRun.query_id == query_id))).all()
    if run_ids:
        await db.execute(delete(ToolCall).where(ToolCall.run_id.in_(run_ids)))
        from src.models.agent import TraceEvent

        await db.execute(delete(TraceEvent).where(TraceEvent.run_id.in_(run_ids)))
        await db.execute(delete(RetrievalResult).where(RetrievalResult.query_id == query_id))
        await db.execute(delete(AgentRun).where(AgentRun.id.in_(run_ids)))
    await db.execute(delete(Feedback).where(Feedback.query_id == query_id))
    await db.execute(delete(Query).where(Query.id == query_id))
    await db.commit()
    return ConversationMutationResponse(query_id=query_id, status="accepted")
