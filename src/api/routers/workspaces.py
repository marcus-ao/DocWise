"""Workspace listing API used by the frontend workspace selector."""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from src.api.deps import DbSession
from src.models.workspace import Workspace
from src.schemas.frontend import WorkspaceItem, WorkspaceListResponse

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=WorkspaceListResponse)
async def list_workspaces(db: DbSession) -> WorkspaceListResponse:
    workspaces = (
        await db.scalars(
            select(Workspace).where(Workspace.is_active.is_(True)).order_by(Workspace.slug)
        )
    ).all()
    items = [
        WorkspaceItem(
            id=workspace.id,
            slug=workspace.slug,
            name=workspace.name,
            workspace_type=workspace.workspace_type.value,
            project_name=workspace.project_name,
            description=workspace.description,
            is_active=workspace.is_active,
        )
        for workspace in workspaces
    ]
    return WorkspaceListResponse(items=items)
