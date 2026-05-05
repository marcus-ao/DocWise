"""Observability tracer — structured trace writes to local DB + optional Langfuse."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.redactor import redact_secrets
from src.config.settings import settings
from src.db.session import async_session_factory
from src.models.agent import AgentRun, ToolCall, TraceEvent
from src.models.base import (
    AgentRunStatus,
    RetrievalStage,
    RouteType,
    ToolCallStatus,
    TraceEventStatus,
)
from src.models.query import Query, RetrievalResult

logger = structlog.get_logger(__name__)

_CONTENT_TRUNCATE_LEN = 200
_MAX_LOG_ENTRIES = 20

_langfuse_instance = None


# ============================================================
# Internal helpers
# ============================================================


def _to_uuid(value: str | UUID) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _redact_summary(data: dict | None) -> dict | None:
    if data is None:
        return None
    try:
        raw = json.dumps(data, ensure_ascii=False, default=str)
        cleaned = redact_secrets(raw)
        result = json.loads(cleaned)
        _truncate_long_strings(result)
        return result
    except Exception:
        return {"redacted": True}


def _cap_tool_output(output_json: dict | None) -> dict | None:
    if output_json is None:
        return None
    capped = _redact_summary(output_json)
    if not isinstance(capped, dict):
        return capped
    entries = capped.get("entries")
    if isinstance(entries, list) and len(entries) > _MAX_LOG_ENTRIES:
        capped["entries"] = entries[:_MAX_LOG_ENTRIES]
        capped["entries_truncated"] = True
    return capped


def _sanitize_citations(citations: list[dict] | None) -> list[dict] | None:
    if citations is None:
        return None
    redacted = _redact_summary({"citations": citations})
    if not isinstance(redacted, dict):
        return None
    cleaned = redacted.get("citations")
    return cleaned if isinstance(cleaned, list) else None


def _truncate_long_strings(obj: dict | list, max_len: int = _CONTENT_TRUNCATE_LEN) -> None:
    if isinstance(obj, dict):
        for key, val in obj.items():
            if isinstance(val, str) and len(val) > max_len:
                obj[key] = val[:max_len] + "..."
            elif isinstance(val, (dict, list)):
                _truncate_long_strings(val, max_len)
    elif isinstance(obj, list):
        for i, val in enumerate(obj):
            if isinstance(val, str) and len(val) > max_len:
                obj[i] = val[:max_len] + "..."
            elif isinstance(val, (dict, list)):
                _truncate_long_strings(val, max_len)


async def _query_exists(session: AsyncSession, query_id: UUID) -> bool:
    return await session.scalar(select(Query.id).where(Query.id == query_id)) is not None


async def _agent_run_exists(session: AsyncSession, run_id: UUID) -> bool:
    return await session.scalar(select(AgentRun.id).where(AgentRun.id == run_id)) is not None


def _langfuse_client():
    global _langfuse_instance
    if _langfuse_instance is not None:
        return _langfuse_instance
    if not settings.langfuse_enabled:
        return None
    try:
        from langfuse import Langfuse

        _langfuse_instance = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        return _langfuse_instance
    except Exception as exc:
        logger.warning("langfuse_init_failed", error=str(exc))
        return None


async def _langfuse_create_trace(run_id: str, query: str) -> None:
    try:
        client = _langfuse_client()
        if client is None:
            return
        client.trace(id=run_id, name="agent_run", input={"query": query})
    except Exception as exc:
        logger.warning("langfuse_create_trace_failed", error=str(exc))


async def _langfuse_complete_trace(run_id: str, status: str) -> None:
    try:
        client = _langfuse_client()
        if client is None:
            return
        client.trace(id=run_id, metadata={"status": status})
    except Exception as exc:
        logger.warning("langfuse_complete_trace_failed", error=str(exc))


async def _langfuse_write_span(
    run_id: str, name: str, input_data: dict | None, output_data: dict | None, latency_ms: int,
) -> None:
    try:
        client = _langfuse_client()
        if client is None:
            return
        trace = client.trace(id=run_id)
        trace.span(name=name, input=input_data, output=output_data, metadata={"latency_ms": latency_ms})
    except Exception as exc:
        logger.warning("langfuse_write_span_failed", error=str(exc), span_name=name)


# ============================================================
# Public API
# ============================================================

async def create_agent_run(
    query_id: str | UUID,
    original_query: str,
    workspace_slug: str | None = None,
) -> str:
    """Create agent_runs record (status=running), return run_id. Never throws."""
    run_id = str(uuid.uuid4())
    try:
        async with async_session_factory() as session:
            qid = _to_uuid(query_id)
            existing = await session.scalar(select(Query).where(Query.id == qid))
            if existing is None:
                session.add(Query(
                    id=qid,
                    original_query=original_query,
                    workspace_slug=workspace_slug,
                    is_archived=False,
                ))
                await session.flush()

            rid = UUID(run_id)
            session.add(AgentRun(
                id=rid,
                query_id=qid,
                original_query=original_query,
                status=AgentRunStatus.running,
                langfuse_trace_id=run_id,
                started_at=datetime.now(UTC),
            ))
            await session.commit()

        if settings.langfuse_enabled:
            asyncio.create_task(_langfuse_create_trace(run_id, original_query))

        await logger.ainfo("agent_run_created", run_id=run_id, query_id=str(query_id))
    except Exception as exc:
        await logger.awarning("create_agent_run_failed", error=str(exc), query_id=str(query_id))
    return run_id


async def complete_agent_run(
    run_id: str | UUID,
    status: str,
    answer: str | None = None,
    citations: list[dict] | None = None,
    route: str | None = None,
    route_confidence: float | None = None,
    workspace_policy: str | None = None,
    workspace_ids: list[str] | None = None,
    confidence_score: float | None = None,
    refused: bool = False,
    refusal_reason: str | None = None,
    latency_ms: int | None = None,
    error_message: str | None = None,
    model_summary: dict | None = None,
    token_usage: dict | None = None,
    langfuse_trace_id: str | None = None,
) -> None:
    """Update agent_runs to terminal state. Never throws."""
    try:
        rid = _to_uuid(run_id)
        async with async_session_factory() as session:
            agent_run = await session.scalar(select(AgentRun).where(AgentRun.id == rid))
            if agent_run is None:
                await logger.awarning("complete_agent_run_not_found", run_id=str(run_id))
                return

            agent_run.status = AgentRunStatus(status)
            agent_run.answer = answer
            agent_run.final_citations = _sanitize_citations(citations)
            agent_run.route = RouteType(route) if route else None
            agent_run.route_confidence = route_confidence
            agent_run.workspace_policy = workspace_policy
            agent_run.workspace_ids = workspace_ids
            agent_run.confidence_score = confidence_score
            agent_run.refused = refused
            agent_run.refusal_reason = refusal_reason
            agent_run.ended_at = datetime.now(UTC)
            agent_run.latency_ms = latency_ms
            agent_run.error_message = error_message
            agent_run.model_summary = model_summary
            agent_run.token_usage = token_usage
            if langfuse_trace_id:
                agent_run.langfuse_trace_id = langfuse_trace_id
            elif agent_run.langfuse_trace_id is None:
                agent_run.langfuse_trace_id = str(rid)

            query = await session.scalar(
                select(Query).where(Query.id == agent_run.query_id)
            )
            if query is not None:
                query.answer = answer
                query.route = RouteType(route) if route else None
                query.route_confidence = route_confidence
                query.confidence_score = confidence_score
                query.refused = refused
                query.refusal_reason = refusal_reason

            await session.commit()

        if settings.langfuse_enabled:
            asyncio.create_task(_langfuse_complete_trace(str(run_id), status))

        await logger.ainfo("agent_run_completed", run_id=str(run_id), status=status)
    except Exception as exc:
        await logger.awarning("complete_agent_run_failed", error=str(exc), run_id=str(run_id))


async def update_agent_run_progress(
    run_id: str | UUID,
    answer: str | None = None,
) -> None:
    """Persist partial streaming answer while the run is still running. Never throws."""
    try:
        rid = _to_uuid(run_id)
        async with async_session_factory() as session:
            agent_run = await session.scalar(select(AgentRun).where(AgentRun.id == rid))
            if agent_run is None:
                await logger.awarning("update_agent_run_progress_not_found", run_id=str(run_id))
                return

            agent_run.answer = answer

            query = await session.scalar(select(Query).where(Query.id == agent_run.query_id))
            if query is not None:
                query.answer = answer

            await session.commit()

        await logger.ainfo("agent_run_progress_updated", run_id=str(run_id), answer_len=len(answer or ""))
    except Exception as exc:
        await logger.awarning("update_agent_run_progress_failed", error=str(exc), run_id=str(run_id))


async def write_trace_event(
    run_id: str | UUID,
    node_name: str,
    sequence_no: int,
    status: str,
    input_summary: dict,
    output_summary: dict,
    latency_ms: int,
    error_message: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Write a trace_event to local DB. Never throws."""
    try:
        rid = _to_uuid(run_id)
        now = datetime.now(UTC)
        async with async_session_factory() as session:
            if not await _agent_run_exists(session, rid):
                await logger.awarning(
                    "write_trace_event_skipped_missing_run",
                    run_id=str(run_id),
                    node=node_name,
                )
                return
            session.add(TraceEvent(
                run_id=rid,
                node_name=node_name,
                sequence_no=sequence_no,
                status=TraceEventStatus(status),
                started_at=now,
                ended_at=now,
                latency_ms=latency_ms,
                input_summary=_redact_summary(input_summary),
                output_summary=_redact_summary(output_summary),
                error_message=error_message,
                trace_metadata=metadata,
            ))
            await session.commit()

        if settings.langfuse_enabled:
            asyncio.create_task(_langfuse_write_span(
                str(run_id), node_name, input_summary, output_summary, latency_ms,
            ))
    except Exception as exc:
        await logger.awarning(
            "write_trace_event_failed", error=str(exc), run_id=str(run_id), node=node_name,
        )


async def write_retrieval_result(
    query_id: str | UUID,
    run_id: str | UUID,
    chunk_id: str | UUID,
    chunk_uid: str,
    document_id: str | UUID,
    workspace_id: str | UUID,
    vector_score: float | None = None,
    keyword_score: float | None = None,
    rrf_score: float | None = None,
    rerank_score: float | None = None,
    final_rank: int | None = None,
    retrieval_stage: str = "rrf",
) -> None:
    """Write a retrieval_result to local DB. Never throws."""
    try:
        qid = _to_uuid(query_id)
        rid = _to_uuid(run_id)
        async with async_session_factory() as session:
            if not await _query_exists(session, qid):
                await logger.awarning(
                    "write_retrieval_result_skipped_missing_query",
                    query_id=str(query_id),
                    run_id=str(run_id),
                    chunk_uid=chunk_uid,
                )
                return
            if not await _agent_run_exists(session, rid):
                await logger.awarning(
                    "write_retrieval_result_skipped_missing_run",
                    query_id=str(query_id),
                    run_id=str(run_id),
                    chunk_uid=chunk_uid,
                )
                return
            session.add(RetrievalResult(
                query_id=qid,
                run_id=rid,
                chunk_id=_to_uuid(chunk_id),
                chunk_uid=chunk_uid,
                document_id=_to_uuid(document_id),
                workspace_id=_to_uuid(workspace_id),
                vector_score=vector_score,
                keyword_score=keyword_score,
                rrf_score=rrf_score,
                rerank_score=rerank_score,
                final_rank=final_rank,
                retrieval_stage=RetrievalStage(retrieval_stage),
            ))
            await session.commit()
    except Exception as exc:
        await logger.awarning(
            "write_retrieval_result_failed", error=str(exc),
            run_id=str(run_id), chunk_uid=chunk_uid,
        )


async def write_tool_call(
    run_id: str | UUID,
    tool_name: str,
    call_index: int,
    input_json: dict,
    output_json: dict | None = None,
    status: str = "success",
    latency_ms: int | None = None,
    error_message: str | None = None,
) -> None:
    """Write a tool_call to local DB. Never throws."""
    try:
        rid = _to_uuid(run_id)
        now = datetime.now(UTC)
        async with async_session_factory() as session:
            if not await _agent_run_exists(session, rid):
                await logger.awarning(
                    "write_tool_call_skipped_missing_run",
                    run_id=str(run_id),
                    tool_name=tool_name,
                )
                return
            session.add(ToolCall(
                run_id=rid,
                tool_name=tool_name,
                call_index=call_index,
                input_json=_redact_summary(input_json) or {},
                output_json=_cap_tool_output(output_json),
                status=ToolCallStatus(status),
                latency_ms=latency_ms,
                error_message=error_message,
                started_at=now,
                ended_at=now,
            ))
            await session.commit()

        if settings.langfuse_enabled:
            asyncio.create_task(_langfuse_write_span(
                str(run_id), f"tool:{tool_name}", input_json, output_json, latency_ms or 0,
            ))
    except Exception as exc:
        await logger.awarning(
            "write_tool_call_failed", error=str(exc),
            run_id=str(run_id), tool_name=tool_name,
        )
