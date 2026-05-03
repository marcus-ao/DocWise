"""Workspace scope selection node."""
from __future__ import annotations

import re
import time

from langchain_core.runnables import RunnableConfig
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent._tracer_stub import write_trace_event
from src.agent.state import AgentState
from src.db.session import async_session_factory
from src.models.base import WorkspaceType
from src.models.workspace import Workspace


async def scope_selector(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
    start = time.perf_counter()
    policy = state.get("workspace_policy", "public_only")
    workspace_ids: list[str] = []
    selected_project = state.get("selected_project")

    async with async_session_factory() as session:
        public_ws = await _get_workspace_by_type(session, WorkspaceType.public_tech)
        mock_ws = await _get_workspace_by_type(session, WorkspaceType.mock_ops)
        project_ws = await _resolve_project_workspace(session, state)

        if policy == "none":
            workspace_ids = []
        elif policy == "public_only":
            workspace_ids = [str(public_ws.id)] if public_ws else []
        elif policy == "selected_project_only":
            workspace_ids = [str(project_ws.id)] if project_ws else []
        elif policy == "selected_project_plus_public":
            if project_ws:
                workspace_ids.append(str(project_ws.id))
            if public_ws:
                workspace_ids.append(str(public_ws.id))
        if state.get("route") in {"troubleshooting", "runbook_generation"} and mock_ws:
            selected_project = selected_project or (project_ws.project_name if project_ws else None)

    state["workspace_ids"] = list(dict.fromkeys(workspace_ids))
    state["selected_project"] = selected_project
    await write_trace_event(
        run_id=state["trace_id"],
        node_name="scope_selector",
        sequence_no=3,
        status="success",
        input_summary={"policy": policy},
        output_summary={"workspace_ids": state["workspace_ids"], "selected_project": selected_project},
        latency_ms=int((time.perf_counter() - start) * 1000),
    )
    return state


async def _get_workspace_by_type(session: AsyncSession, workspace_type: WorkspaceType) -> Workspace | None:
    return await session.scalar(
        select(Workspace).where(Workspace.workspace_type == workspace_type, Workspace.is_active.is_(True)).limit(1)
    )


async def _resolve_project_workspace(session: AsyncSession, state: AgentState) -> Workspace | None:
    explicit = state.get("selected_workspace_name")
    if explicit:
        workspace = await session.scalar(
            select(Workspace).where(Workspace.slug == explicit, Workspace.is_active.is_(True)).limit(1)
        )
        if workspace:
            return workspace

    project_name = state.get("selected_project") or _infer_project_name(state)
    if not project_name:
        return None
    normalized = _normalize(project_name)
    rows = (
        await session.scalars(
            select(Workspace).where(
                Workspace.workspace_type == WorkspaceType.project_pack,
                Workspace.is_active.is_(True),
            )
        )
    ).all()
    for workspace in rows:
        values = {
            _normalize(workspace.slug),
            _normalize(workspace.name),
            _normalize(workspace.project_name),
        }
        if normalized in values or any(normalized in value for value in values):
            return workspace
    return None


def _infer_project_name(state: AgentState) -> str | None:
    text = " ".join(
        [
            state.get("original_query", ""),
            state.get("rewritten_query", ""),
            " ".join(str(item) for item in state.get("key_entities", [])),
        ]
    ).lower()
    if "airflow" in text or "data-platform" in text:
        return "data-platform"
    if "backstage" in text:
        return "backstage-portal"
    if "fastapi" in text or "api-gateway" in text:
        return "api-gateway"
    return None


def _normalize(value: str | None) -> str:
    return re.sub(r"\s+", "-", (value or "").strip().lower().replace("_", "-"))

