"""Evaluation API routes."""
from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, status
from sqlalchemy import func, select

from src.api.deps import DbSession
from src.document.ingestion import _enqueue_arq_job
from src.models.base import EntityType, JobStatus, JobType
from src.models.eval import EvalCase, EvalResult
from src.models.job import BackgroundJob
from src.schemas.eval import EvalRunRequest, EvalRunResponse, EvalSummary
from src.schemas.frontend import EvalBadCaseItem, EvalBadCaseListResponse, EvalTrendItem, EvalTrendsResponse

router = APIRouter(prefix="/eval", tags=["eval"])


@router.get("/count")
async def count_eval_cases(db: DbSession) -> dict[str, int]:
    return {"total_cases": int(await db.scalar(select(func.count()).select_from(EvalCase)) or 0)}


@router.post("/run", response_model=EvalRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_eval(db: DbSession, request: EvalRunRequest) -> EvalRunResponse:
    eval_run_id = request.run_id or uuid4()
    job = BackgroundJob(
        job_type=JobType.eval_run,
        status=JobStatus.queued,
        entity_type=EntityType.eval,
        entity_id=eval_run_id,
        input_json={
            "eval_run_id": str(eval_run_id),
            "retry_failed": request.retry_failed,
            "case_filter": request.case_filter,
        },
        progress={"stage": "queued", "percent": 0, "current": 0, "total": 1, "message": "Queued eval run"},
    )
    db.add(job)
    await db.flush()
    job.arq_job_id = await _enqueue_arq_job("process_eval_run", job.id)
    await db.commit()
    return EvalRunResponse(eval_run_id=UUID(str(eval_run_id)), job_id=job.id, status="queued")


@router.get("/results", response_model=list[EvalSummary])
async def list_eval_results(db: DbSession) -> list[EvalSummary]:
    run_ids = (await db.scalars(select(EvalResult.run_id).distinct().limit(20))).all()
    summaries: list[EvalSummary] = []
    for run_id in run_ids:
        rows = (await db.scalars(select(EvalResult).where(EvalResult.run_id == run_id))).all()
        if not rows:
            continue
        completed = [row for row in rows if row.status == "completed"]
        summaries.append(
            EvalSummary(
                run_id=UUID(str(run_id)),
                retrieval_hit_rate_at_5=_avg(row.retrieval_hit_rate for row in completed),
                mrr_at_5=_avg(row.mrr for row in completed),
                workspace_accuracy=_avg_bool(row.workspace_accuracy for row in completed),
                citation_validity=_avg(row.citation_validity for row in completed),
                citation_coverage=_avg(row.citation_coverage for row in completed),
                refusal_accuracy=_avg_bool(row.refusal_accuracy for row in completed),
                tool_call_accuracy=_avg(row.tool_call_accuracy for row in completed),
                answer_correctness_avg=_avg(row.answer_correctness for row in completed),
                faithfulness_avg=_avg(row.faithfulness for row in completed),
                latency_p50_ms=None,
                latency_p95_ms=None,
                total_cases=len(rows),
                completed_cases=len(completed),
                failed_cases=len([row for row in rows if row.status == "error"]),
                bad_case_count=len([row for row in rows if row.bad_case_types]),
            )
        )
    return summaries


@router.get("/trends", response_model=EvalTrendsResponse)
async def list_eval_trends(db: DbSession, limit: int = 10) -> EvalTrendsResponse:
    latest_created_at = func.max(EvalResult.created_at).label("created_at")
    run_rows = (
        await db.execute(
            select(EvalResult.run_id, latest_created_at)
            .group_by(EvalResult.run_id)
            .order_by(latest_created_at.desc())
            .limit(limit)
        )
    ).all()

    trends: list[EvalTrendItem] = []
    for index, (run_id, created_at) in enumerate(reversed(run_rows), start=1):
        rows = (await db.scalars(select(EvalResult).where(EvalResult.run_id == run_id))).all()
        completed = [row for row in rows if row.status == "completed"]
        trends.append(
            EvalTrendItem(
                run_id=UUID(str(run_id)),
                run_name=f"Run {index}",
                hit_rate_at_5=_avg(row.retrieval_hit_rate for row in completed),
                mrr=_avg(row.mrr for row in completed),
                citation_accuracy=_avg(row.citation_validity for row in completed),
                bad_case_count=len([row for row in rows if row.bad_case_types]),
                total_cases=len(rows),
                created_at=created_at,
            )
        )
    return EvalTrendsResponse(trends=trends)


@router.get("/bad-cases", response_model=EvalBadCaseListResponse)
async def list_bad_cases(db: DbSession, limit: int = 20) -> EvalBadCaseListResponse:
    rows = (
        await db.execute(
            select(EvalResult, EvalCase)
            .join(EvalCase, EvalCase.id == EvalResult.case_id)
            .where(EvalResult.bad_case_types.is_not(None))
            .order_by(EvalResult.created_at.desc())
            .limit(limit)
        )
    ).all()
    items = [
        EvalBadCaseItem(
            eval_result_id=result.id,
            run_id=UUID(str(result.run_id)),
            case_id=case.case_id,
            query=case.query,
            bad_case_types=[str(item) for item in result.bad_case_types or []],
            error_message=result.error_message,
            created_at=result.created_at,
        )
        for result, case in rows
        if result.bad_case_types
    ]
    total = int(
        await db.scalar(
            select(func.count()).select_from(EvalResult).where(EvalResult.bad_case_types.is_not(None))
        )
        or 0
    )
    return EvalBadCaseListResponse(items=items, total=total)


def _avg(values) -> float | None:
    cleaned = [float(value) for value in values if value is not None]
    return sum(cleaned) / len(cleaned) if cleaned else None


def _avg_bool(values) -> float | None:
    cleaned = [bool(value) for value in values if value is not None]
    return sum(1 for value in cleaned if value) / len(cleaned) if cleaned else None
