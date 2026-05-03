"""Background job status helpers."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.base import JobStatus
from src.models.job import BackgroundJob


async def get_background_job(session: AsyncSession, job_id: str | UUID) -> BackgroundJob | None:
    return await session.scalar(select(BackgroundJob).where(BackgroundJob.id == UUID(str(job_id))))


async def update_job_progress(
    session: AsyncSession,
    job_id: str | UUID | None,
    stage: str,
    percent: int,
    current: int,
    total: int,
    message: str,
) -> None:
    if job_id is None:
        return
    job = await get_background_job(session, job_id)
    if job is None:
        return
    job.progress = {
        "stage": stage,
        "percent": max(0, min(100, percent)),
        "current": current,
        "total": total,
        "message": message,
    }
    job.updated_at = datetime.now(UTC)
    await session.flush()


async def update_job_status(
    session: AsyncSession,
    job_id: str | UUID | None,
    status: JobStatus,
    error_message: str | None = None,
    result_json: dict | None = None,
) -> None:
    if job_id is None:
        return
    job = await get_background_job(session, job_id)
    if job is None:
        return
    now = datetime.now(UTC)
    job.status = status
    job.error_message = error_message
    if result_json is not None:
        job.result_json = result_json
    if status == JobStatus.running and job.started_at is None:
        job.started_at = now
    if status in {JobStatus.succeeded, JobStatus.failed, JobStatus.cancelled}:
        job.finished_at = now
    job.updated_at = now
    await session.flush()
