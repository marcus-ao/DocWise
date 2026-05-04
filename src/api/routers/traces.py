"""Frontend-oriented trace timeline API routes."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from src.api.deps import DbSession
from src.models.agent import AgentRun, TraceEvent
from src.schemas.frontend import TraceListItem, TraceListResponse, TraceTimelineNode, TraceTimelineResponse

router = APIRouter(prefix="/traces", tags=["traces"])


@router.get("", response_model=TraceListResponse)
async def list_traces(
    db: DbSession,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> TraceListResponse:
    rows = (
        await db.scalars(select(AgentRun).order_by(AgentRun.created_at.desc()).limit(limit).offset(offset))
    ).all()
    total = int(await db.scalar(select(func.count()).select_from(AgentRun)) or 0)
    return TraceListResponse(
        items=[
            TraceListItem(
                run_id=run.id,
                query_id=run.query_id,
                query=run.original_query,
                route=str(getattr(run.route, "value", run.route)) if run.route else None,
                status=str(getattr(run.status, "value", run.status)),
                latency_ms=run.latency_ms,
                created_at=run.created_at,
                started_at=run.started_at,
                ended_at=run.ended_at,
            )
            for run in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{run_id}/timeline", response_model=TraceTimelineResponse)
async def get_trace_timeline(db: DbSession, run_id: UUID) -> TraceTimelineResponse:
    run = await db.get(AgentRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trace not found")
    events = (
        await db.scalars(
            select(TraceEvent).where(TraceEvent.run_id == run_id).order_by(TraceEvent.sequence_no)
        )
    ).all()

    base_time = _base_time(run, list(events))
    nodes = [_timeline_node(event, base_time, index) for index, event in enumerate(events)]
    total_latency_ms = int(run.latency_ms or max((node.end_time_ms for node in nodes), default=0))
    return TraceTimelineResponse(run_id=run_id, total_latency_ms=total_latency_ms, nodes=nodes)


def _base_time(run: AgentRun, events: list[TraceEvent]) -> datetime:
    event_starts = [event.started_at for event in events if event.started_at is not None]
    if event_starts:
        return min(event_starts)
    return run.started_at or run.created_at


def _offset_ms(value: datetime | None, base_time: datetime, fallback_ms: int) -> int:
    if value is None:
        return fallback_ms
    return max(0, int((value - base_time).total_seconds() * 1000))


def _node_type(node_name: str) -> str:
    if "router" in node_name:
        return "route"
    if "retriever" in node_name or "reranker" in node_name:
        return "retrieval"
    if "tool" in node_name:
        return "tool"
    if "answer" in node_name or "generator" in node_name or "rewriter" in node_name:
        return "llm"
    if "evidence" in node_name or "citation" in node_name or "validator" in node_name:
        return "check"
    return "node"


def _indent_level(node_name: str) -> int:
    if "tool_executor" in node_name:
        return 2
    if "retriever" in node_name or "reranker" in node_name or "tool" in node_name:
        return 1
    return 0


def _metadata(event: TraceEvent) -> dict:
    metadata: dict = {}
    for item in (event.input_summary, event.output_summary, event.trace_metadata):
        if isinstance(item, dict):
            metadata.update(item)
    return metadata


def _timeline_node(event: TraceEvent, base_time: datetime, index: int) -> TraceTimelineNode:
    fallback_start = index * 25
    start_ms = _offset_ms(event.started_at, base_time, fallback_start)
    duration_ms = int(event.latency_ms or 0)
    end_ms = _offset_ms(event.ended_at, base_time, start_ms + duration_ms)
    if end_ms <= start_ms:
        end_ms = start_ms + max(duration_ms, 1)
    return TraceTimelineNode(
        id=str(event.id),
        title=event.node_name,
        type=_node_type(event.node_name),
        start_time_ms=start_ms,
        end_time_ms=end_ms,
        duration_ms=end_ms - start_ms,
        indent_level=_indent_level(event.node_name),
        status=str(getattr(event.status, "value", event.status)),
        metadata=_metadata(event),
        error_message=event.error_message,
    )
