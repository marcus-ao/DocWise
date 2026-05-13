from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.agent.nodes.scope_selector import scope_selector
from src.agent.state import create_initial_state
from src.models.base import WorkspaceType
from src.models.workspace import Workspace


def _workspace(slug: str, workspace_type: WorkspaceType, project_name: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        slug=slug,
        name=slug,
        workspace_type=workspace_type,
        project_name=project_name,
        description=None,
        is_active=True,
    )


class _ScalarRows:
    def __init__(self, items: list[object]) -> None:
        self._items = items

    def all(self) -> list[object]:
        return list(self._items)


class _FakeSession:
    def __init__(self, workspaces: list[object]) -> None:
        self._workspaces = workspaces

    async def scalars(self, stmt: object) -> _ScalarRows:
        return _ScalarRows(self._workspaces)


class _FakeSessionContext:
    def __init__(self, workspaces: list[object]) -> None:
        self._session = _FakeSession(workspaces)

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


def _scope_selector_patches(workspaces: list[object]):
    return (
        patch("src.agent.nodes.scope_selector.async_session_factory", return_value=_FakeSessionContext(workspaces)),
        patch("src.agent.nodes.scope_selector.write_trace_event", AsyncMock()),
    )


def _scope_workspaces() -> list[object]:
    return [
        _workspace("public_tech", WorkspaceType.public_tech),
        _workspace("project_airflow", WorkspaceType.project_pack, project_name="data-platform"),
        _workspace("project_backstage", WorkspaceType.project_pack, project_name="backstage-portal"),
        _workspace("project_fastapi", WorkspaceType.project_pack, project_name="api-gateway"),
        _workspace("project_openclaw", WorkspaceType.project_pack, project_name="openclaw"),
        _workspace("project_affine", WorkspaceType.project_pack, project_name="affine"),
        _workspace("project_mineru", WorkspaceType.project_pack, project_name="mineru"),
        _workspace("mock_ops", WorkspaceType.mock_ops),
    ]


def test_workspace_documents_relationship_is_lazy_select() -> None:
    assert Workspace.documents.property.lazy == "select"


@pytest.mark.asyncio
async def test_scope_selector_auto_alias_adds_project_public_and_mock_ops() -> None:
    state = create_initial_state("Airflow scheduler 心跳丢失怎么排查？", trace_id=str(uuid4()))
    state["route"] = "troubleshooting"
    state["workspace_policy"] = "selected_project_plus_public"

    with _scope_selector_patches(_scope_workspaces())[0], _scope_selector_patches(_scope_workspaces())[1]:
        result = await scope_selector(state)

    assert result["selected_project"] == "project_airflow"
    assert result["effective_workspace_slugs"] == ["project_airflow", "public_tech", "mock_ops"]
    assert result["scope_reason_code"] == "auto_project_matched"
    assert result["display_workspace_slug"] == "project_airflow"


@pytest.mark.asyncio
async def test_scope_selector_explicit_public_merges_project_alias() -> None:
    state = create_initial_state("Airflow DAG 的 schedule_interval 怎么配？", trace_id=str(uuid4()))
    state["route"] = "project_specific"
    state["workspace_policy"] = "selected_project_plus_public"
    state["selected_workspace_slug"] = "public_tech"

    with _scope_selector_patches(_scope_workspaces())[0], _scope_selector_patches(_scope_workspaces())[1]:
        result = await scope_selector(state)

    assert result["selected_project"] == "project_airflow"
    assert result["effective_workspace_slugs"] == ["public_tech", "project_airflow"]
    assert result["scope_reason_code"] == "explicit_plus_alias"


@pytest.mark.asyncio
async def test_scope_selector_explicit_project_ignores_conflicting_alias() -> None:
    state = create_initial_state("backstage catalog-info.yaml 怎么写？", trace_id=str(uuid4()))
    state["route"] = "project_specific"
    state["workspace_policy"] = "selected_project_plus_public"
    state["selected_workspace_slug"] = "project_airflow"

    with _scope_selector_patches(_scope_workspaces())[0], _scope_selector_patches(_scope_workspaces())[1]:
        result = await scope_selector(state)

    assert result["selected_project"] == "project_airflow"
    assert result["effective_workspace_slugs"] == ["project_airflow", "public_tech"]
    assert result["scope_reason_code"] == "explicit_conflict_ignored"
    assert "project_backstage" not in result["effective_workspace_slugs"]


@pytest.mark.asyncio
async def test_scope_selector_inherits_workspace_scope_from_previous_turn() -> None:
    state = create_initial_state("那超时应该怎么配？", trace_id=str(uuid4()))
    state["route"] = "project_specific"
    state["workspace_policy"] = "selected_project_plus_public"
    state["recent_turns"] = [
        {
            "turn_index": 2,
            "run_id": str(uuid4()),
            "query": "Airflow DAG 配置规范是什么？",
            "answer": "Use scheduler defaults.",
            "citations": [],
            "tool_facts": [],
            "effective_workspace_slugs": ["project_airflow", "public_tech"],
        }
    ]

    with _scope_selector_patches(_scope_workspaces())[0], _scope_selector_patches(_scope_workspaces())[1]:
        result = await scope_selector(state)

    assert result["selected_project"] == "project_airflow"
    assert result["effective_workspace_slugs"] == ["project_airflow", "public_tech"]
    assert result["scope_reason_code"] == "inherited_from_turn"
    assert result["scope_reason_params"] == {"route": "project_specific", "inherited_from_turn": 2, "project_slug": "project_airflow"}


@pytest.mark.asyncio
async def test_scope_selector_route_downgrade_keeps_public_and_mock_ops_for_troubleshooting() -> None:
    state = create_initial_state("最近错误率有点高，该怎么排查？", trace_id=str(uuid4()))
    state["route"] = "troubleshooting"
    state["workspace_policy"] = "selected_project_plus_public"

    with _scope_selector_patches(_scope_workspaces())[0], _scope_selector_patches(_scope_workspaces())[1]:
        result = await scope_selector(state)

    assert result["selected_project"] is None
    assert result["effective_workspace_slugs"] == ["public_tech", "mock_ops"]
    assert result["scope_reason_code"] == "route_downgrade"


@pytest.mark.asyncio
async def test_scope_selector_projects_workspace_ids_from_effective_slugs() -> None:
    workspaces = _scope_workspaces()
    state = create_initial_state("Airflow scheduler 心跳丢失怎么排查？", trace_id=str(uuid4()))
    state["route"] = "troubleshooting"
    state["workspace_policy"] = "selected_project_plus_public"

    with _scope_selector_patches(workspaces)[0], _scope_selector_patches(workspaces)[1]:
        result = await scope_selector(state)

    expected_ids = [
        str(next(workspace.id for workspace in workspaces if workspace.slug == slug))
        for slug in result["effective_workspace_slugs"]
    ]
    assert result["workspace_ids"] == expected_ids


@pytest.mark.asyncio
async def test_scope_selector_matches_openclaw_aliases() -> None:
    state = create_initial_state("OpenClaw control-plane 部署文档在哪？", trace_id=str(uuid4()))
    state["route"] = "project_specific"
    state["workspace_policy"] = "selected_project_plus_public"

    with _scope_selector_patches(_scope_workspaces())[0], _scope_selector_patches(_scope_workspaces())[1]:
        result = await scope_selector(state)

    assert result["selected_project"] == "project_openclaw"
    assert result["effective_workspace_slugs"] == ["project_openclaw", "public_tech"]


@pytest.mark.asyncio
async def test_scope_selector_matches_affine_aliases() -> None:
    state = create_initial_state("toeverything AFFiNE sync schema 是什么？", trace_id=str(uuid4()))
    state["route"] = "project_specific"
    state["workspace_policy"] = "selected_project_plus_public"

    with _scope_selector_patches(_scope_workspaces())[0], _scope_selector_patches(_scope_workspaces())[1]:
        result = await scope_selector(state)

    assert result["selected_project"] == "project_affine"
    assert result["effective_workspace_slugs"] == ["project_affine", "public_tech"]


@pytest.mark.asyncio
async def test_scope_selector_matches_mineru_aliases() -> None:
    state = create_initial_state("使用 opendatalab pdf-extract 解析 PDF 失败怎么办？", trace_id=str(uuid4()))
    state["route"] = "project_specific"
    state["workspace_policy"] = "selected_project_plus_public"

    with _scope_selector_patches(_scope_workspaces())[0], _scope_selector_patches(_scope_workspaces())[1]:
        result = await scope_selector(state)

    assert result["selected_project"] == "project_mineru"
    assert result["effective_workspace_slugs"] == ["project_mineru", "public_tech"]
