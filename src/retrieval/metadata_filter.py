"""Workspace and lightweight metadata filtering helpers."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.base import WorkspaceType
from src.models.workspace import Workspace


def detect_query_language(query: str) -> str:
    chinese_chars = sum(1 for char in query if "\u4e00" <= char <= "\u9fff")
    if chinese_chars >= 2:
        return "zh"
    return "en"


async def resolve_workspace_ids(session: AsyncSession, workspace_ids: list[str]) -> list[UUID]:
    if not workspace_ids:
        return []

    resolved: list[UUID] = []
    slugs: list[str] = []
    for item in workspace_ids:
        try:
            resolved.append(UUID(str(item)))
        except ValueError:
            slugs.append(str(item))

    if slugs:
        rows = (
            await session.scalars(
                select(Workspace).where(Workspace.slug.in_(slugs), Workspace.is_active.is_(True))
            )
        ).all()
        resolved.extend(row.id for row in rows)
    return resolved


async def get_public_workspace_id(session: AsyncSession) -> str | None:
    workspace = await session.scalar(
        select(Workspace).where(
            Workspace.workspace_type == WorkspaceType.public_tech,
            Workspace.is_active.is_(True),
        )
    )
    return str(workspace.id) if workspace else None

