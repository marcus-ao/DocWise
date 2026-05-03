"""Seed default workspaces."""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from src.db.session import async_session_factory
from src.models.base import WorkspaceType
from src.models.workspace import Workspace

WORKSPACES = [
    {
        "slug": "public_tech",
        "name": "Public Tech Docs",
        "workspace_type": WorkspaceType.public_tech,
        "project_name": None,
        "description": "Shared public technical documentation.",
    },
    {
        "slug": "project_airflow",
        "name": "Airflow Data Platform",
        "workspace_type": WorkspaceType.project_pack,
        "project_name": "data-platform",
        "description": "Airflow project-specific operations knowledge.",
    },
    {
        "slug": "project_backstage",
        "name": "Backstage Developer Portal",
        "workspace_type": WorkspaceType.project_pack,
        "project_name": "backstage-portal",
        "description": "Backstage project-specific operations knowledge.",
    },
    {
        "slug": "project_fastapi",
        "name": "FastAPI Gateway",
        "workspace_type": WorkspaceType.project_pack,
        "project_name": "api-gateway",
        "description": "FastAPI gateway project-specific operations knowledge.",
    },
    {
        "slug": "mock_ops",
        "name": "Mock Operations",
        "workspace_type": WorkspaceType.mock_ops,
        "project_name": "mock-ops",
        "description": "Deterministic mock monitoring and log data.",
    },
]


async def main() -> None:
    inserted = 0
    updated = 0
    async with async_session_factory() as session:
        for item in WORKSPACES:
            workspace = await session.scalar(select(Workspace).where(Workspace.slug == item["slug"]))
            if workspace is None:
                session.add(Workspace(**item))
                inserted += 1
            else:
                for key, value in item.items():
                    setattr(workspace, key, value)
                workspace.is_active = True
                updated += 1
        await session.commit()
    print(f"Seeded workspaces: inserted={inserted}, updated={updated}")


if __name__ == "__main__":
    asyncio.run(main())

