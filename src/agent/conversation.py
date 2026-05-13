from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import settings
from src.llm.client import chat_completion
from src.models.agent import AgentRun, ToolCall
from src.models.base import AgentRunStatus
from src.models.query import Query
from src.models.workspace import Workspace
from src.observability.tracer import create_agent_run

logger = structlog.get_logger(__name__)

CANCELLED_RUN_MARKER = "cancelled_by_user"


@dataclass(slots=True)
class PreparedConversationRun:
    conversation_id: UUID
    run_id: str
    turn_index: int
    parent_run_id: UUID | None


@dataclass(slots=True)
class ConversationContextPayload:
    recent_turns: list[dict]
    context_summary: str | None
    summary_used: bool
    summary_cache_hit: bool
    summary_source: str
    summary_latency_ms: int | None
    loaded_turn_count: int
    excluded_run_ids: dict[str, list[str]]


def conversation_title_from_query(query: str) -> str:
    normalized = " ".join(query.split())
    if len(normalized) <= 48:
        return normalized or "未命名对话"
    return f"{normalized[:45]}..."


async def prepare_stream_conversation_run(
    session: AsyncSession,
    *,
    conversation_id: UUID | None,
    original_query: str,
    workspace_slug: str | None,
) -> PreparedConversationRun:
    last_error: IntegrityError | None = None
    for attempt in range(2):
        try:
            return await _prepare_stream_conversation_run_once(
                session,
                conversation_id=conversation_id,
                original_query=original_query,
                workspace_slug=workspace_slug,
            )
        except IntegrityError as exc:
            last_error = exc
            await session.rollback()
            if attempt == 1:
                raise
            await logger.awarning(
                "prepare_stream_conversation_run_retry",
                conversation_id=str(conversation_id) if conversation_id else None,
                error=str(exc),
            )
    if last_error is not None:
        raise last_error
    raise RuntimeError("unreachable")


async def load_conversation_context(
    session: AsyncSession,
    *,
    query_id: str | UUID,
    current_run_id: str | UUID,
) -> ConversationContextPayload:
    qid = _to_uuid(query_id)
    rid = _to_uuid(current_run_id)
    query = await session.get(Query, qid)
    if query is None:
        return ConversationContextPayload(
            recent_turns=[],
            context_summary=None,
            summary_used=False,
            summary_cache_hit=False,
            summary_source="none",
            summary_latency_ms=None,
            loaded_turn_count=0,
            excluded_run_ids={"current": [str(rid)], "cancelled": [], "failed_empty": [], "running": []},
        )

    runs = list(
        (
            await session.scalars(
                select(AgentRun)
                .where(AgentRun.query_id == qid)
                .order_by(AgentRun.turn_index.asc(), AgentRun.created_at.asc(), AgentRun.id.asc())
            )
        ).all()
    )
    valid_runs, excluded = _filter_context_runs(runs, current_run_id=rid)
    if not valid_runs:
        return ConversationContextPayload(
            recent_turns=[],
            context_summary=None,
            summary_used=False,
            summary_cache_hit=False,
            summary_source="none",
            summary_latency_ms=None,
            loaded_turn_count=0,
            excluded_run_ids=excluded,
        )

    tool_calls_by_run = await _tool_calls_by_run(
        session,
        [run.id for run in valid_runs],
    )
    workspace_slugs_by_run = await _workspace_slugs_by_run(session, valid_runs)
    history_limit = max(settings.context_loader_history_limit, settings.context_loader_recent_turns)
    history_window = valid_runs[-history_limit:]
    recent_runs = history_window[-settings.context_loader_recent_turns :]
    recent_turns = [
        _turn_payload(
            run,
            tool_calls_by_run.get(run.id, []),
            workspace_slugs_by_run.get(run.id, []),
        )
        for run in recent_runs
    ]

    older_runs = valid_runs[:-settings.context_loader_recent_turns]
    summary_source = "none"
    summary_cache_hit = False
    summary_latency_ms: int | None = None
    context_summary = None
    if older_runs:
        if query.context_summary:
            context_summary = query.context_summary
            summary_source = "cached"
            summary_cache_hit = True
        else:
            start = time.perf_counter()
            context_summary = await _generate_context_summary(
                older_runs,
                tool_calls_by_run,
            )
            summary_latency_ms = int((time.perf_counter() - start) * 1000)
            if context_summary:
                query.context_summary = context_summary
                await session.commit()
                summary_source = "generated"
            else:
                summary_source = "none"
    return ConversationContextPayload(
        recent_turns=recent_turns,
        context_summary=context_summary,
        summary_used=bool(context_summary),
        summary_cache_hit=summary_cache_hit,
        summary_source=summary_source,
        summary_latency_ms=summary_latency_ms,
        loaded_turn_count=min(len(valid_runs), history_limit),
        excluded_run_ids=excluded,
    )


async def refresh_context_summary(query_id: str | UUID) -> None:
    from src.db.session import async_session_factory

    qid = _to_uuid(query_id)
    async with async_session_factory() as session:
        query = await session.get(Query, qid)
        if query is None:
            return
        runs = list(
            (
                await session.scalars(
                    select(AgentRun)
                    .where(AgentRun.query_id == qid)
                    .order_by(AgentRun.turn_index.asc(), AgentRun.created_at.asc(), AgentRun.id.asc())
                )
            ).all()
        )
        valid_runs, _ = _filter_context_runs(runs, current_run_id=None)
        older_runs = valid_runs[:-settings.context_loader_recent_turns]
        if not older_runs:
            query.context_summary = None
            await session.commit()
            return
        tool_calls_by_run = await _tool_calls_by_run(session, [run.id for run in older_runs])
        summary = await _generate_context_summary(older_runs, tool_calls_by_run)
        # Preserve the previous persisted summary when a refresh attempt returns
        # empty output. Otherwise a transient empty LLM response on a later turn
        # can erase a valid summary that was already being used by context_loader.
        if summary is not None:
            query.context_summary = summary
            await session.commit()


async def _prepare_stream_conversation_run_once(
    session: AsyncSession,
    *,
    conversation_id: UUID | None,
    original_query: str,
    workspace_slug: str | None,
) -> PreparedConversationRun:
    qid = conversation_id or uuid4()
    query = await session.scalar(
        select(Query).where(Query.id == qid).with_for_update()
    )
    if query is None:
        query = Query(
            id=qid,
            original_query=original_query,
            workspace_slug=workspace_slug,
            conversation_title=conversation_title_from_query(original_query),
            is_archived=False,
        )
        session.add(query)
        await session.flush()

    latest_run = await session.scalar(_latest_run_stmt(qid))
    turn_index = int(latest_run.turn_index) + 1 if latest_run is not None else 0
    parent_run_id = latest_run.id if latest_run is not None else None
    run_id = await create_agent_run(
        query_id=qid,
        original_query=original_query,
        workspace_slug=workspace_slug,
        turn_index=turn_index,
        parent_run_id=parent_run_id,
        conversation_title=query.conversation_title or conversation_title_from_query(original_query),
        db_session=session,
    )
    await session.commit()
    return PreparedConversationRun(
        conversation_id=qid,
        run_id=run_id,
        turn_index=turn_index,
        parent_run_id=parent_run_id,
    )


def _latest_run_stmt(query_id: UUID) -> Select[tuple[AgentRun]]:
    return (
        select(AgentRun)
        .where(AgentRun.query_id == query_id)
        .order_by(AgentRun.turn_index.desc(), AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(1)
    )


def _filter_context_runs(
    runs: list[AgentRun],
    *,
    current_run_id: UUID | None,
) -> tuple[list[AgentRun], dict[str, list[str]]]:
    excluded = {
        "current": [],
        "cancelled": [],
        "failed_empty": [],
        "running": [],
    }
    valid: list[AgentRun] = []
    for run in runs:
        if current_run_id is not None and run.id == current_run_id:
            excluded["current"].append(str(run.id))
            continue
        if run.status == AgentRunStatus.running:
            excluded["running"].append(str(run.id))
            continue
        if run.error_message == CANCELLED_RUN_MARKER:
            excluded["cancelled"].append(str(run.id))
            continue
        if run.status == AgentRunStatus.failed and not (run.answer or "").strip():
            excluded["failed_empty"].append(str(run.id))
            continue
        valid.append(run)
    return valid, excluded


async def _tool_calls_by_run(
    session: AsyncSession,
    run_ids: list[UUID],
) -> dict[UUID, list[ToolCall]]:
    if not run_ids:
        return {}
    rows = list(
        (
            await session.scalars(
                select(ToolCall)
                .where(ToolCall.run_id.in_(run_ids))
                .order_by(ToolCall.run_id.asc(), ToolCall.call_index.asc())
            )
        ).all()
    )
    grouped: dict[UUID, list[ToolCall]] = {}
    for row in rows:
        grouped.setdefault(row.run_id, []).append(row)
    return grouped


async def _workspace_slugs_by_run(
    session: AsyncSession,
    runs: list[AgentRun],
) -> dict[UUID, list[str]]:
    raw_values: list[str] = []
    for run in runs:
        raw_values.extend(str(item) for item in run.workspace_ids or [])
    if not raw_values:
        return {run.id: [] for run in runs}

    resolved_by_uuid: dict[str, str] = {}
    uuid_values: list[UUID] = []
    for item in raw_values:
        try:
            uuid_values.append(UUID(str(item)))
        except ValueError:
            continue
    if uuid_values:
        rows = list(
            (
                await session.scalars(
                    select(Workspace).where(Workspace.id.in_(uuid_values), Workspace.is_active.is_(True))
                )
            ).all()
        )
        resolved_by_uuid = {str(row.id): row.slug for row in rows}

    grouped: dict[UUID, list[str]] = {}
    for run in runs:
        slugs: list[str] = []
        for item in run.workspace_ids or []:
            text = str(item)
            slugs.append(resolved_by_uuid.get(text, text))
        grouped[run.id] = list(dict.fromkeys(slugs))
    return grouped


def _turn_payload(
    run: AgentRun,
    tool_calls: list[ToolCall],
    effective_workspace_slugs: list[str],
) -> dict[str, Any]:
    return {
        "turn_index": int(run.turn_index),
        "run_id": str(run.id),
        "query": str(run.original_query or ""),
        "answer": str(run.answer or ""),
        "citations": list(run.final_citations or []),
        "effective_workspace_slugs": effective_workspace_slugs,
        "tool_facts": _extract_tool_facts(tool_calls),
    }


def _extract_tool_facts(tool_calls: list[ToolCall]) -> list[str]:
    selected: list[tuple[int, str]] = []
    for call in tool_calls:
        tool_name = str(call.tool_name)
        if tool_name == "search_docs":
            continue
        status = str(getattr(call.status, "value", call.status))
        if status == "success":
            summary = _success_tool_fact(tool_name, call.output_json or {})
            priority = 0 if tool_name in {"query_service_status", "query_mock_logs"} else 1
            if summary:
                selected.append((priority, summary[:200]))
        else:
            selected.append((2, f"{tool_name}: {status}"))
    selected.sort(key=lambda item: item[0])
    return [item[1] for item in selected[:2]]


def _success_tool_fact(tool_name: str, output_json: dict) -> str:
    if tool_name == "query_service_status":
        service_name = str(output_json.get("service_name") or "")
        status = str(output_json.get("status") or "")
        alerts = output_json.get("active_alerts")
        alert_count = len(alerts) if isinstance(alerts, list) else 0
        return f"{tool_name}: service={service_name or 'unknown'} status={status or 'unknown'} alerts={alert_count}"
    if tool_name == "query_mock_logs":
        service_name = str(output_json.get("service_name") or "")
        matched_count = output_json.get("matched_count")
        level = str(output_json.get("level") or "")
        time_range = str(output_json.get("time_range") or "")
        return (
            f"{tool_name}: service={service_name or 'unknown'} matched={matched_count or 0} "
            f"level={level or 'unknown'} range={time_range or 'unknown'}"
        )
    if tool_name == "query_project_manifest":
        service_name = str(output_json.get("service_name") or "")
        owner = str(output_json.get("owner") or "")
        project_name = str(output_json.get("project_name") or "")
        parts = [part for part in [project_name, service_name, owner] if part]
        return f"{tool_name}: {' / '.join(parts)}" if parts else tool_name
    summary = output_json.get("summary") or output_json.get("message") or output_json.get("status")
    return f"{tool_name}: {summary}" if summary is not None else tool_name


async def _generate_context_summary(
    runs: list[AgentRun],
    tool_calls_by_run: dict[UUID, list[ToolCall]],
) -> str | None:
    rendered_turns: list[str] = []
    for run in runs:
        tool_facts = _extract_tool_facts(tool_calls_by_run.get(run.id, []))
        rendered_turns.append(
            "\n".join(
                [
                    f"[turn {run.turn_index}] User: {str(run.original_query or '').strip()}",
                    f"[turn {run.turn_index}] Assistant: {str(run.answer or '').strip()}",
                    (
                        f"[turn {run.turn_index}] Tool facts: {'; '.join(tool_facts)}"
                        if tool_facts
                        else ""
                    ),
                ]
            ).strip()
        )
    if not rendered_turns:
        return None
    response = await chat_completion(
        [
            {
                "role": "system",
                "content": (
                    "你是 DocWise 的会话摘要器。请把更早轮次的用户问题、结论、关键对象、"
                    "工具观察和未解决点压缩为简洁摘要。不要杜撰，不要加入新建议。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请总结以下历史对话，保留后续 follow-up 所需的对象、前提、结论和未解决点，"
                    f"输出不超过 {settings.context_summary_max_chars} 个字符：\n\n"
                    + "\n\n".join(rendered_turns)
                ),
            },
        ],
        model="fast",
        temperature=0,
        max_tokens=max(128, settings.context_summary_max_chars),
        timeout=20.0,
    )
    summary = str(response.get("content") or "").strip()
    if not summary:
        return None
    return summary[: settings.context_summary_max_chars]


def _to_uuid(value: str | UUID) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))
