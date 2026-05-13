from __future__ import annotations

import re
import time
from typing import Literal

from langchain_core.runnables import RunnableConfig
from sqlalchemy import select
from sqlalchemy.orm import load_only, noload

from src.agent._tracer_stub import write_trace_event
from src.agent.state import AgentState
from src.config.settings import settings
from src.db.session import async_session_factory
from src.models.base import WorkspaceType
from src.models.workspace import Workspace

ScopeReasonCode = Literal[
    "explicit_only",
    "explicit_plus_alias",
    "auto_project_matched",
    "auto_route_default",
    "route_downgrade",
    "explicit_conflict_ignored",
    "inherited_from_turn",
    "out_of_scope",
]

ProjectRouteName = Literal["project_specific", "troubleshooting", "runbook_generation"]

_PROJECT_ALIAS_TO_SLUG: dict[str, str] = {
    "airflow": "project_airflow",
    "data-platform": "project_airflow",
    "scheduler": "project_airflow",
    "dag": "project_airflow",
    "worker": "project_airflow",
    "backstage": "project_backstage",
    "backstage-portal": "project_backstage",
    "catalog": "project_backstage",
    "plugin": "project_backstage",
    "fastapi": "project_fastapi",
    "api-gateway": "project_fastapi",
    "gateway": "project_fastapi",
    "openclaw": "project_openclaw",
    "claw": "project_openclaw",
    "control-plane": "project_openclaw",
    "affine": "project_affine",
    "toeverything": "project_affine",
    "mineru": "project_mineru",
    "opendatalab": "project_mineru",
    "pdf-extract": "project_mineru",
}

_PROJECT_ROUTES: set[ProjectRouteName] = {
    "project_specific",
    "troubleshooting",
    "runbook_generation",
}

_SCOPE_LIMIT_BY_ROUTE: dict[str, str] = {
    "tech_general": "scope_max_workspaces_tech_general",
    "project_specific": "scope_max_workspaces_project_specific",
    "troubleshooting": "scope_max_workspaces_troubleshooting",
    "runbook_generation": "scope_max_workspaces_runbook_generation",
}


async def scope_selector(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
    start = time.perf_counter()
    route = str(state.get("route") or "tech_general")
    policy = state.get("workspace_policy", "public_only")

    async with async_session_factory() as session:
        workspaces = list(
            (
                await session.scalars(
                    select(Workspace)
                    .options(
                        load_only(
                            Workspace.id,
                            Workspace.slug,
                            Workspace.name,
                            Workspace.workspace_type,
                            Workspace.project_name,
                            Workspace.description,
                            Workspace.is_active,
                        ),
                        noload(Workspace.documents),
                    )
                    .where(Workspace.is_active.is_(True))
                    .order_by(Workspace.slug.asc())
                )
            ).all()
        )

    workspaces_by_slug = {workspace.slug: workspace for workspace in workspaces}
    project_workspaces = {
        workspace.slug: workspace
        for workspace in workspaces
        if workspace.workspace_type == WorkspaceType.project_pack
    }
    public_workspace = next(
        (workspace for workspace in workspaces if workspace.workspace_type == WorkspaceType.public_tech),
        None,
    )
    mock_workspace = next(
        (workspace for workspace in workspaces if workspace.workspace_type == WorkspaceType.mock_ops),
        None,
    )

    explicit_workspace_slug = _normalize_slug(state.get("selected_workspace_slug"))
    if explicit_workspace_slug and explicit_workspace_slug not in workspaces_by_slug:
        explicit_workspace_slug = None

    alias_hits = _alias_hits(state, project_workspaces)
    inherited = _inherited_scope(state, project_workspaces) if _should_inherit(state, explicit_workspace_slug, alias_hits) else None
    inherited_project_slug = inherited["project_slug"] if inherited else None
    selected_project_slug, alias_chosen = _choose_project_slug(
        explicit_workspace_slug=explicit_workspace_slug,
        alias_hits=alias_hits,
        inherited_project_slug=inherited_project_slug,
        project_workspaces=project_workspaces,
    )

    effective_workspace_slugs, reason_code, reason_params = _build_effective_scope(
        route=route,
        explicit_workspace_slug=explicit_workspace_slug,
        selected_project_slug=selected_project_slug,
        alias_hits=alias_hits,
        alias_chosen=alias_chosen,
        inherited=inherited,
        public_slug=public_workspace.slug if public_workspace else None,
        mock_slug=mock_workspace.slug if mock_workspace else None,
        project_workspaces=project_workspaces,
    )
    effective_workspace_slugs = _cap_scope(route, effective_workspace_slugs)
    # `effective_workspace_slugs` is the semantic source of truth for runtime scope.
    # `workspace_ids` is only the DB-facing projection consumed by retrieval.
    workspace_ids = _workspace_ids_for_slugs(effective_workspace_slugs, workspaces_by_slug)
    display_workspace_slug = _display_workspace_slug(
        route=route,
        explicit_workspace_slug=explicit_workspace_slug,
        selected_project_slug=selected_project_slug,
        public_slug=public_workspace.slug if public_workspace else None,
    )

    state["workspace_ids"] = workspace_ids
    state["selected_project"] = selected_project_slug
    state["selected_workspace_slug"] = explicit_workspace_slug
    state["display_workspace_slug"] = display_workspace_slug
    state["effective_workspace_slugs"] = effective_workspace_slugs
    state["scope_reason_code"] = reason_code
    state["scope_reason_params"] = reason_params
    state["workspace_alias_hits"] = alias_hits
    state["working_context_preview"] = state.get("working_context_preview")

    elapsed = int((time.perf_counter() - start) * 1000)
    await write_trace_event(
        run_id=state["trace_id"],
        node_name="scope_selector",
        sequence_no=4,
        status="success",
        input_summary={
            "policy": policy,
            "route": route,
            "explicit_workspace_slug": explicit_workspace_slug,
        },
        output_summary={
            "workspace_ids": workspace_ids,
            "effective_workspace_slugs": effective_workspace_slugs,
            "selected_project": selected_project_slug,
            "display_workspace_slug": display_workspace_slug,
        },
        metadata={
            "explicit_workspace_slug": explicit_workspace_slug,
            "alias_hits": alias_hits,
            "alias_chosen": alias_chosen,
            "effective_workspace_slugs": effective_workspace_slugs,
            "scope_reason_code": reason_code,
            "scope_reason_params": reason_params,
            "inherited_from_turn": inherited["turn_index"] if inherited else None,
            "display_workspace_slug": display_workspace_slug,
        },
        latency_ms=elapsed,
    )
    return state


def _normalize_slug(value: str | None) -> str | None:
    normalized = re.sub(r"\s+", "-", (value or "").strip().lower())
    return normalized or None


def _normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", "-", (value or "").strip().lower().replace("_", "-"))


def _alias_hits(state: AgentState, project_workspaces: dict[str, Workspace]) -> list[str]:
    texts: list[str] = [
        state.get("effective_query", ""),
        state.get("rewritten_query", ""),
        state.get("original_query", ""),
        " ".join(str(item) for item in state.get("key_entities", [])),
    ]

    normalized_text = _normalize_text(" ".join(texts))
    hits: list[str] = []
    for alias, slug in _PROJECT_ALIAS_TO_SLUG.items():
        if slug not in project_workspaces:
            continue
        if alias in normalized_text:
            hits.append(slug)
    seen: set[str] = set()
    ordered_hits: list[str] = []
    for slug in hits:
        if slug not in seen:
            ordered_hits.append(slug)
            seen.add(slug)
    return ordered_hits


def _should_inherit(
    state: AgentState,
    explicit_workspace_slug: str | None,
    alias_hits: list[str],
) -> bool:
    if explicit_workspace_slug or alias_hits:
        return False
    if not settings.scope_enable_followup_inheritance:
        return False
    route = str(state.get("route") or "tech_general")
    return route in _PROJECT_ROUTES


def _inherited_scope(state: AgentState, project_workspaces: dict[str, Workspace]) -> dict | None:
    for turn in reversed(state.get("recent_turns") or []):
        slugs = [str(item) for item in turn.get("effective_workspace_slugs") or []]
        if not slugs:
            continue
        inherited_project_slug = next((slug for slug in slugs if slug in project_workspaces), None)
        return {
            "turn_index": turn.get("turn_index"),
            "effective_workspace_slugs": slugs,
            "project_slug": inherited_project_slug,
        }
    return None


def _choose_project_slug(
    *,
    explicit_workspace_slug: str | None,
    alias_hits: list[str],
    inherited_project_slug: str | None,
    project_workspaces: dict[str, Workspace],
) -> tuple[str | None, str | None]:
    if explicit_workspace_slug in project_workspaces:
        return explicit_workspace_slug, alias_hits[0] if alias_hits else None
    if alias_hits:
        return alias_hits[0], alias_hits[0]
    if inherited_project_slug:
        return inherited_project_slug, None
    return None, None


def _build_effective_scope(
    *,
    route: str,
    explicit_workspace_slug: str | None,
    selected_project_slug: str | None,
    alias_hits: list[str],
    alias_chosen: str | None,
    inherited: dict | None,
    public_slug: str | None,
    mock_slug: str | None,
    project_workspaces: dict[str, Workspace],
) -> tuple[list[str], ScopeReasonCode, dict]:
    if route == "out_of_scope":
        return [], "out_of_scope", {"route": route}

    effective_slugs: list[str] = []
    params: dict[str, object] = {"route": route}
    explicit_is_project = explicit_workspace_slug in project_workspaces
    conflicting_aliases = [
        slug
        for slug in alias_hits
        if explicit_is_project and slug != explicit_workspace_slug
    ]

    if explicit_workspace_slug:
        effective_slugs.append(explicit_workspace_slug)
        params["explicit"] = explicit_workspace_slug

    if selected_project_slug and selected_project_slug not in effective_slugs:
        if not explicit_is_project or selected_project_slug == explicit_workspace_slug:
            effective_slugs.append(selected_project_slug)

    if route == "tech_general":
        if public_slug:
            effective_slugs.append(public_slug)
    elif route == "project_specific":
        if selected_project_slug:
            effective_slugs.append(selected_project_slug)
        if settings.scope_include_public_for_project_specific and public_slug:
            effective_slugs.append(public_slug)
    elif route == "troubleshooting":
        if selected_project_slug:
            effective_slugs.append(selected_project_slug)
        if public_slug:
            effective_slugs.append(public_slug)
        if mock_slug:
            effective_slugs.append(mock_slug)
    elif route == "runbook_generation":
        if selected_project_slug:
            effective_slugs.append(selected_project_slug)
        if public_slug:
            effective_slugs.append(public_slug)

    effective_slugs = list(dict.fromkeys(slug for slug in effective_slugs if slug))

    if explicit_is_project and conflicting_aliases:
        params["alias_hits"] = alias_hits
        params["project_slug"] = explicit_workspace_slug
        return effective_slugs, "explicit_conflict_ignored", params
    if explicit_workspace_slug and alias_chosen and explicit_workspace_slug != alias_chosen:
        params["alias_hits"] = alias_hits
        params["alias_chosen"] = alias_chosen
        params["project_slug"] = selected_project_slug
        return effective_slugs, "explicit_plus_alias", params
    if explicit_workspace_slug:
        params["project_slug"] = selected_project_slug
        return effective_slugs, "explicit_only", params
    if alias_chosen:
        params["alias_hits"] = alias_hits
        params["alias_chosen"] = alias_chosen
        params["project_slug"] = selected_project_slug
        return effective_slugs, "auto_project_matched", params
    if inherited:
        params["inherited_from_turn"] = inherited.get("turn_index")
        params["project_slug"] = selected_project_slug
        return effective_slugs, "inherited_from_turn", params
    if route in _PROJECT_ROUTES and not selected_project_slug:
        return effective_slugs, "route_downgrade", params
    return effective_slugs, "auto_route_default", params


def _cap_scope(route: str, effective_workspace_slugs: list[str]) -> list[str]:
    setting_name = _SCOPE_LIMIT_BY_ROUTE.get(route)
    if not setting_name:
        return effective_workspace_slugs
    limit = int(getattr(settings, setting_name))
    return effective_workspace_slugs[:limit]


def _display_workspace_slug(
    *,
    route: str,
    explicit_workspace_slug: str | None,
    selected_project_slug: str | None,
    public_slug: str | None,
) -> str | None:
    if route == "out_of_scope":
        return None
    if explicit_workspace_slug:
        return explicit_workspace_slug
    if selected_project_slug:
        return selected_project_slug
    return public_slug


def _workspace_ids_for_slugs(
    effective_workspace_slugs: list[str],
    workspaces_by_slug: dict[str, Workspace],
) -> list[str]:
    return [
        str(workspaces_by_slug[slug].id)
        for slug in effective_workspace_slugs
        if slug in workspaces_by_slug
    ]
