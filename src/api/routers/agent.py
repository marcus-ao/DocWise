"""Agent run and trace API routes."""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from src.agent.graph import run_agent
from src.api.citations import citations_from_final, citations_from_retrieval_rows
from src.api.deps import DbSession
from src.models.agent import AgentRun, ToolCall, TraceEvent
from src.models.query import RetrievalResult
from src.schemas.agent import AgentRunRequest, AgentRunStatusResponse, AgentTraceResponse
from src.schemas.shared import RetrievalResultItem, ToolCallItem, TraceEventItem

router = APIRouter(prefix="/agent", tags=["agent"])


def _enum_value(value: object, default: str = "") -> str:
    if value is None:
        return default
    return str(getattr(value, "value", value))


def _trace_item(row: TraceEvent) -> TraceEventItem:
    return TraceEventItem(
        node_name=row.node_name,
        sequence_no=row.sequence_no,
        status=_enum_value(row.status, "success"),
        latency_ms=row.latency_ms,
        input_summary=row.input_summary,
        output_summary=row.output_summary,
        error_message=row.error_message,
    )


def _tool_item(row: ToolCall) -> ToolCallItem:
    return ToolCallItem(
        tool_name=row.tool_name,
        call_index=row.call_index,
        input_json=row.input_json,
        output_json=row.output_json,
        status=_enum_value(row.status, "success"),
        latency_ms=row.latency_ms,
        error_message=row.error_message,
    )


def _retrieval_item(row: RetrievalResult) -> RetrievalResultItem:
    return RetrievalResultItem(
        chunk_uid=row.chunk_uid,
        document_title="",
        section_path=None,
        vector_score=row.vector_score,
        keyword_score=row.keyword_score,
        rrf_score=row.rrf_score,
        rerank_score=row.rerank_score,
        final_rank=row.final_rank,
    )


@router.post("/run", response_model=AgentRunStatusResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_agent_route(request: AgentRunRequest) -> AgentRunStatusResponse:
    query_id = uuid4()
    state = await run_agent(request.query, query_id=str(query_id), workspace_slug=request.workspace_slug)
    run_id = UUID(str(state.get("trace_id") or uuid4()))
    status_value = "refused" if state.get("refused") else "succeeded"
    if state.get("error") and not state.get("answer"):
        status_value = "failed"
    from datetime import UTC, datetime

    return AgentRunStatusResponse(
        id=run_id,
        query_id=query_id,
        status=status_value,
        route=state.get("route"),
        latency_ms=None,
        created_at=datetime.now(UTC),
    )


@router.get("/runs/{run_id}/status", response_model=AgentRunStatusResponse)
async def get_run_status(db: DbSession, run_id: UUID) -> AgentRunStatusResponse:
    run = await db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")
    return AgentRunStatusResponse(
        id=run.id,
        query_id=run.query_id,
        status=_enum_value(run.status, "running"),
        route=_enum_value(run.route, "") or None,
        latency_ms=run.latency_ms,
        created_at=run.created_at,
    )


@router.get("/runs/{run_id}/trace", response_model=AgentTraceResponse)
async def get_run_trace(db: DbSession, run_id: UUID) -> AgentTraceResponse:
    run = await db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")
    trace_events = (
        await db.scalars(select(TraceEvent).where(TraceEvent.run_id == run_id).order_by(TraceEvent.sequence_no))
    ).all()
    retrieval_results = (
        await db.scalars(
            select(RetrievalResult).where(RetrievalResult.run_id == run_id).order_by(RetrievalResult.final_rank)
        )
    ).all()
    tool_calls = (
        await db.scalars(select(ToolCall).where(ToolCall.run_id == run_id).order_by(ToolCall.call_index))
    ).all()
    citations = citations_from_final(run.final_citations) or citations_from_retrieval_rows(list(retrieval_results))
    return AgentTraceResponse(
        run_id=run.id,
        status=_enum_value(run.status, "running"),
        route=_enum_value(run.route, "") or None,
        answer=run.answer,
        trace_events=[_trace_item(row) for row in trace_events],
        retrieval_results=[_retrieval_item(row) for row in retrieval_results],
        tool_calls=[_tool_item(row) for row in tool_calls],
        citations=citations,
        model_summary=run.model_summary,
        token_usage=run.token_usage,
    )
