"""Chat API routes, including LangGraph-to-SSE streaming."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Protocol, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from openai import RateLimitError
from sqlalchemy import func, select

from src.agent.graph import build_agent_graph, run_agent
from src.agent.state import RetryableError, RetryBudget, create_initial_state
from src.api.citations import citation_from_dict, citations_from_final, citations_from_retrieval_rows
from src.api.deps import DbSession
from src.models.agent import AgentRun, ToolCall
from src.models.feedback import Feedback
from src.models.query import Query, RetrievalResult
from src.observability import complete_agent_run, create_agent_run
from src.schemas.chat import ChatRequest, ChatResponse, FeedbackRequest, FeedbackResponse
from src.schemas.frontend import (
    ChatConversationDetail,
    ChatConversationListItem,
    ChatConversationListResponse,
    ChatConversationMessage,
)
from src.schemas.shared import ToolCallItem

router = APIRouter(prefix="/chat", tags=["chat"])
HEARTBEAT_INTERVAL_SECONDS = 30.0


class EventStreamGraph(Protocol):
    def astream_events(self, input: dict, **kwargs: object) -> AsyncIterator[dict]: ...


def _value(value: object, default: object = None) -> object:
    return default if value is None else value


def _json_default(value: object) -> str:
    return str(value)


def format_sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False, default=_json_default)}\n\n"


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


def _reasoning_title(node_name: str) -> str:
    return {
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

    if event_type == "on_chain_end" and name == "query_router":
        return format_sse(
            "route",
            {
                "route": str(state.get("route", "tech_general")),
                "confidence": float(state.get("route_confidence") or 0.0),
                "workspace_policy": str(state.get("workspace_policy", "public_only")),
                "workspace_ids": list(state.get("workspace_ids") or []),
                "selected_project": state.get("selected_project"),
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


async def _events_with_heartbeat(graph: EventStreamGraph, state: dict) -> AsyncIterator[dict]:
    iterator = graph.astream_events(
        dict(state),
        version="v2",
        config={"configurable": {"retry_budget": RetryBudget(max_total_retries=3)}},
    ).__aiter__()
    next_event_task: asyncio.Future[dict] | None = None
    while True:
        if next_event_task is None:
            next_event_task = asyncio.ensure_future(iterator.__anext__())
        done, _pending = await asyncio.wait({next_event_task}, timeout=HEARTBEAT_INTERVAL_SECONDS)
        if not done:
            yield {"event": "heartbeat", "name": "heartbeat", "data": {}}
            continue
        try:
            yield next_event_task.result()
            next_event_task = None
        except StopAsyncIteration:
            return


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
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    async def event_generator() -> AsyncIterator[str]:
        start = time.perf_counter()
        query_id = str(uuid4())
        run_id = str(uuid4())
        state = create_initial_state(original_query=request.query, trace_id=run_id)
        state["query_id"] = query_id
        if request.workspace_slug:
            state["selected_workspace_name"] = request.workspace_slug
        final_state: dict = dict(state)
        out_of_scope = False
        try:
            run_id = await create_agent_run(
                query_id=query_id,
                original_query=request.query,
                workspace_slug=request.workspace_slug,
            )
            state["trace_id"] = run_id
            final_state["trace_id"] = run_id
            graph = cast(EventStreamGraph, build_agent_graph())
            async for event in _events_with_heartbeat(graph, dict(state)):
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
                    yield mapped
        except Exception as error:
            await complete_agent_run(
                run_id=run_id,
                status="failed",
                answer=None,
                error_message=str(error)[:500],
            )
            yield format_sse(
                "error",
                {"error_type": _error_type(error), "message": str(error), "run_id": run_id, "node_name": None},
            )
            return

        await complete_agent_run(
            run_id=str(final_state.get("trace_id") or run_id),
            status="refused" if final_state.get("refused") else "succeeded",
            answer=str(final_state.get("answer") or ""),
            citations=final_state.get("citations"),
            route=final_state.get("route"),
            route_confidence=final_state.get("route_confidence"),
            workspace_policy=final_state.get("workspace_policy"),
            workspace_ids=final_state.get("workspace_ids"),
            confidence_score=final_state.get("confidence_score"),
            refused=bool(final_state.get("refused", False)),
            refusal_reason=final_state.get("refusal_reason"),
            latency_ms=int((time.perf_counter() - start) * 1000),
            error_message=final_state.get("error"),
        )

        yield format_sse(
            "done",
            {
                "query_id": query_id,
                "run_id": str(final_state.get("trace_id") or run_id),
                "refused": bool(final_state.get("refused", False)),
                "refusal_reason": final_state.get("refusal_reason"),
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "answer": str(final_state.get("answer") or ""),
            },
        )

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/conversations", response_model=ChatConversationListResponse)
async def list_conversations(
    db: DbSession,
    workspace_slug: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> ChatConversationListResponse:
    stmt = select(Query).order_by(Query.created_at.desc()).limit(limit).offset(offset)
    count_stmt = select(func.count()).select_from(Query)
    if workspace_slug:
        stmt = stmt.where(Query.workspace_slug == workspace_slug)
        count_stmt = count_stmt.where(Query.workspace_slug == workspace_slug)
    rows = (await db.scalars(stmt)).all()
    total = int(await db.scalar(count_stmt) or 0)

    items: list[ChatConversationListItem] = []
    for query in rows:
        run = await db.scalar(
            select(AgentRun).where(AgentRun.query_id == query.id).order_by(AgentRun.created_at.desc()).limit(1)
        )
        updated_at = (run.ended_at or run.created_at) if run else query.created_at
        items.append(
            ChatConversationListItem(
                id=query.id,
                query_id=query.id,
                run_id=run.id if run else None,
                title=_conversation_title(query.original_query),
                workspace_id=query.workspace_slug,
                workspace_slug=query.workspace_slug,
                created_at=query.created_at,
                updated_at=updated_at,
                message_count=2 if (run and run.answer) or query.answer else 1,
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
    run = await db.scalar(
        select(AgentRun).where(AgentRun.query_id == query.id).order_by(AgentRun.created_at.desc()).limit(1)
    )
    retrieval_rows = (await db.scalars(select(RetrievalResult).where(RetrievalResult.query_id == query.id))).all()
    citations = citations_from_final(run.final_citations) if run else []
    if not citations:
        citations = citations_from_retrieval_rows(list(retrieval_rows))

    messages = [
        ChatConversationMessage(
            id=f"{query.id}:user",
            role="user",
            content=query.original_query,
            created_at=query.created_at,
        )
    ]
    answer = str(run.answer or query.answer or "") if run else str(query.answer or "")
    if answer:
        messages.append(
            ChatConversationMessage(
                id=f"{run.id if run else query.id}:assistant",
                role="assistant",
                content=answer,
                citations=citations,
                created_at=(run.ended_at or run.created_at) if run else query.created_at,
            )
        )

    updated_at = (run.ended_at or run.created_at) if run else query.created_at
    return ChatConversationDetail(
        id=query.id,
        query_id=query.id,
        run_id=run.id if run else None,
        title=_conversation_title(query.original_query),
        workspace_id=query.workspace_slug,
        workspace_slug=query.workspace_slug,
        created_at=query.created_at,
        updated_at=updated_at,
        messages=messages,
    )


@router.get("/history")
async def list_chat_history(
    db: DbSession,
    workspace_slug: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, object]:
    stmt = select(Query, AgentRun).join(AgentRun, AgentRun.query_id == Query.id, isouter=True)
    count_stmt = select(Query)
    if workspace_slug:
        stmt = stmt.where(Query.workspace_slug == workspace_slug)
        count_stmt = count_stmt.where(Query.workspace_slug == workspace_slug)
    rows = (await db.execute(stmt.order_by(Query.created_at.desc()).limit(limit).offset(offset))).all()
    total = len((await db.scalars(count_stmt)).all())
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
    retrieval_rows = (await db.scalars(select(RetrievalResult).where(RetrievalResult.query_id == query_id))).all()
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
