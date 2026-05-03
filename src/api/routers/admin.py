"""Admin statistics and index status API routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from src.api.deps import AdminAuth, DbSession
from src.config.settings import settings
from src.models.agent import AgentRun
from src.models.document import Document, DocumentChunk
from src.models.eval import EvalCase, EvalResult
from src.models.query import Query as QueryModel
from src.models.workspace import Workspace
from src.schemas.admin import (
    AdminStatsResponse,
    BadCaseItem,
    BadCaseListResponse,
    IndexStatusResponse,
    IndexWorkspaceItem,
)
from src.schemas.shared import WorkspaceStatsItem

router = APIRouter(prefix="/admin", tags=["admin"])


def _non_empty_bad_case_filter():
    return (
        EvalResult.bad_case_types.is_not(None),
        func.jsonb_array_length(EvalResult.bad_case_types) > 0,
    )


@router.get("/stats", response_model=AdminStatsResponse)
async def get_stats(db: DbSession, _auth: AdminAuth) -> AdminStatsResponse:
    workspaces = (
        await db.scalars(select(Workspace).where(Workspace.is_active.is_(True)).order_by(Workspace.slug))
    ).all()
    workspace_items: list[WorkspaceStatsItem] = []
    for workspace in workspaces:
        document_count = int(
            await db.scalar(select(func.count()).select_from(Document).where(Document.workspace_id == workspace.id))
            or 0
        )
        chunk_count = int(
            await db.scalar(
                select(func.count())
                .select_from(DocumentChunk)
                .where(DocumentChunk.workspace_id == workspace.id, DocumentChunk.is_active.is_(True))
            )
            or 0
        )
        workspace_items.append(
            WorkspaceStatsItem(
                slug=workspace.slug, name=workspace.name, document_count=document_count, chunk_count=chunk_count
            )
        )
    return AdminStatsResponse(
        total_documents=int(await db.scalar(select(func.count()).select_from(Document)) or 0),
        total_chunks=int(
            await db.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.is_active.is_(True)))
            or 0
        ),
        total_queries=int(await db.scalar(select(func.count()).select_from(QueryModel)) or 0),
        total_agent_runs=int(await db.scalar(select(func.count()).select_from(AgentRun)) or 0),
        total_eval_runs=int(await db.scalar(select(func.count(func.distinct(EvalResult.run_id)))) or 0),
        workspaces=workspace_items,
    )


@router.get("/bad-cases", response_model=BadCaseListResponse)
async def list_bad_cases(
    db: DbSession,
    _auth: AdminAuth,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> BadCaseListResponse:
    bad_case_filters = _non_empty_bad_case_filter()
    base = (
        select(EvalCase, EvalResult)
        .join(EvalResult, EvalResult.case_id == EvalCase.id)
        .where(*bad_case_filters)
    )
    rows = (await db.execute(base.order_by(EvalResult.created_at.desc()).limit(limit).offset(offset))).all()
    total = int(
        await db.scalar(select(func.count()).select_from(EvalResult).where(*bad_case_filters)) or 0
    )
    items = [
        BadCaseItem(
            case_id=case.case_id,
            query=case.query,
            route=str(getattr(case.route, "value", case.route)),
            bad_case_types=list(result.bad_case_types or []),
            agent_run_id=result.agent_run_id,
            eval_run_id=UUID(str(result.run_id)),
        )
        for case, result in rows
    ]
    return BadCaseListResponse(items=items, total=total)


@router.get("/index-status", response_model=IndexStatusResponse)
async def get_index_status(db: DbSession, _auth: AdminAuth) -> IndexStatusResponse:
    workspaces = (
        await db.scalars(select(Workspace).where(Workspace.is_active.is_(True)).order_by(Workspace.slug))
    ).all()
    workspace_items: list[IndexWorkspaceItem] = []
    for workspace in workspaces:
        chunk_count = int(
            await db.scalar(
                select(func.count())
                .select_from(DocumentChunk)
                .where(DocumentChunk.workspace_id == workspace.id, DocumentChunk.is_active.is_(True))
            )
            or 0
        )
        latest_indexed_at = await db.scalar(
            select(func.max(Document.indexed_at)).where(Document.workspace_id == workspace.id)
        )
        workspace_items.append(
            IndexWorkspaceItem(slug=workspace.slug, chunk_count=chunk_count, latest_indexed_at=latest_indexed_at)
        )
    return IndexStatusResponse(
        total_chunks=int(await db.scalar(select(func.count()).select_from(DocumentChunk)) or 0),
        active_chunks=int(
            await db.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.is_active.is_(True)))
            or 0
        ),
        inactive_chunks=int(
            await db.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.is_active.is_(False)))
            or 0
        ),
        embedding_model=settings.embedding_model,
        embedding_dim=settings.embedding_dim,
        vector_index_type="ivfflat",
        workspaces=workspace_items,
    )
