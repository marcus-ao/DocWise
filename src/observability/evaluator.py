"""Batch eval runner — load eval cases, invoke Agent, compute metrics, persist results."""
from __future__ import annotations

import time
from uuid import UUID, uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import async_session_factory
from src.models.agent import ToolCall
from src.models.base import JobStatus
from src.models.eval import EvalCase, EvalResult
from src.models.job import BackgroundJob
from src.models.workspace import Workspace
from src.observability.bad_case import classify_bad_cases
from src.observability.metrics import (
    citation_coverage,
    citation_validity,
    hit_rate_at_k,
    mrr_at_k,
    refusal_accuracy,
    tool_call_accuracy,
    workspace_accuracy,
)
from src.tasks.helpers import update_job_progress, update_job_status

logger = structlog.get_logger(__name__)

async def _workspace_slugs_for_ids(session: AsyncSession, workspace_ids: list[str]) -> list[str]:
    if not workspace_ids:
        return []
    result = await session.scalars(select(Workspace).where(Workspace.id.in_(workspace_ids)))
    return [workspace.slug for workspace in result.all()]


def _expected_workspace_slugs(eval_case: EvalCase) -> list[str]:
    expected_workspace_ids = getattr(eval_case, "expected_workspace_ids", None)
    if expected_workspace_ids:
        return [str(item) for item in expected_workspace_ids]
    if eval_case.workspace_slug:
        if eval_case.route.value in {"project_specific", "troubleshooting", "runbook_generation"}:
            return [eval_case.workspace_slug, "public_tech"]
        if eval_case.route.value == "out_of_scope":
            return []
        return [eval_case.workspace_slug]
    if eval_case.route.value == "tech_general":
        return ["public_tech"]
    if eval_case.route.value == "out_of_scope":
        return []
    return []


def _case_filter_expr(case_filter: dict | None):
    if not case_filter:
        return []
    filters = []
    route = case_filter.get("route")
    if route:
        filters.append(EvalCase.route == route)
    tags = case_filter.get("tags")
    if tags:
        tag_list = tags if isinstance(tags, list) else [tags]
        for tag in tag_list:
            filters.append(EvalCase.tags.contains([tag]))
    return filters


async def _extract_metrics(session: AsyncSession, eval_case: EvalCase, final_state: dict) -> dict:
    """Compute all P0 metrics from AgentState output."""
    actual_chunk_uids = [
        c.get("chunk_uid", "") for c in final_state.get("reranked_chunks", [])
    ]
    actual_citations = [
        c.get("chunk_uid", "") for c in final_state.get("citations", [])
    ]
    actual_workspace_ids = [str(item) for item in final_state.get("workspace_ids", [])]
    actual_workspace_slugs = await _workspace_slugs_for_ids(session, actual_workspace_ids)
    actual_tools = [
        r.get("tool_name", "")
        for r in final_state.get("tool_results", [])
    ]
    actually_refused = final_state.get("refused", False)

    expected_chunk_uids = eval_case.expected_chunk_uids or []
    expected_citations = eval_case.expected_citations or []
    expected_workspace_ids = _expected_workspace_slugs(eval_case)
    expected_tools = eval_case.expected_tools or []

    return {
        "retrieval_hit_rate": hit_rate_at_k(expected_chunk_uids, actual_chunk_uids) if expected_chunk_uids else None,
        "mrr": mrr_at_k(expected_chunk_uids, actual_chunk_uids) if expected_chunk_uids else None,
        "workspace_accuracy": (
            workspace_accuracy(expected_workspace_ids, actual_workspace_slugs)
            if expected_workspace_ids else None
        ),
        "citation_validity": citation_validity(actual_citations, actual_chunk_uids) if actual_citations else None,
        "citation_coverage": citation_coverage(expected_citations, actual_citations) if expected_citations else None,
        "refusal_accuracy": refusal_accuracy(eval_case.should_refuse, actually_refused),
        "tool_call_accuracy": tool_call_accuracy(expected_tools, actual_tools) if expected_tools else None,
    }


async def _get_tool_calls_for_run(session: AsyncSession, agent_run_id: UUID) -> list[dict]:
    """Fetch tool call records for bad case classification."""
    result = await session.scalars(
        select(ToolCall).where(ToolCall.run_id == agent_run_id)
    )
    return [{"tool_name": tc.tool_name, "status": tc.status.value} for tc in result.all()]


# ============================================================
# Main entry point
# ============================================================

async def run_eval(job_id: str) -> dict:
    """Main entry point for batch evaluation. Called by arq worker."""
    from src.agent.graph import run_agent

    async with async_session_factory() as session:
        await update_job_status(session, job_id, JobStatus.running)
        await session.commit()

        job = await session.scalar(
            select(BackgroundJob).where(BackgroundJob.id == UUID(job_id))
        )
        input_json = job.input_json or {} if job else {}
        eval_run_id = UUID(input_json.get("eval_run_id", str(uuid4())))
        retry_failed = input_json.get("retry_failed", False)
        case_filter = input_json.get("case_filter")

        if retry_failed:
            failed_results = (
                await session.scalars(
                    select(EvalResult)
                    .where(EvalResult.run_id == eval_run_id, EvalResult.status == "error")
                )
            ).all()
            case_ids = [r.case_id for r in failed_results]
            cases = (
                await session.scalars(select(EvalCase).where(EvalCase.id.in_(case_ids)))
            ).all() if case_ids else []
        else:
            stmt = select(EvalCase)
            for expr in _case_filter_expr(case_filter):
                stmt = stmt.where(expr)
            cases = (await session.scalars(stmt)).all()

        total = len(cases)
        completed = 0
        error_count = 0

        for i, case in enumerate(cases):
            await update_job_progress(
                session, job_id, "running_cases",
                percent=int((i / max(total, 1)) * 100),
                current=i, total=total,
                message=f"Running case {case.case_id}",
            )
            await session.commit()

            try:
                start = time.perf_counter()
                final_state = await run_agent(
                    original_query=case.query,
                    query_id=str(uuid4()),
                    workspace_slug=case.workspace_slug,
                )
                latency_ms = int((time.perf_counter() - start) * 1000)

                metrics = await _extract_metrics(session, case, final_state)
                route_matches = final_state.get("route") == case.route.value

                agent_run_id = UUID(final_state["trace_id"]) if final_state.get("trace_id") else None
                tool_calls = await _get_tool_calls_for_run(session, agent_run_id) if agent_run_id else []

                eval_result_dict = {**metrics, "latency_ms": latency_ms}
                if not route_matches:
                    eval_result_dict["workspace_accuracy"] = False
                bad_types = classify_bad_cases(
                    {"should_refuse": case.should_refuse},
                    eval_result_dict,
                    tool_calls,
                )

                session.add(EvalResult(
                    run_id=eval_run_id,
                    case_id=case.id,
                    agent_run_id=agent_run_id,
                    status="completed",
                    retrieval_hit_rate=metrics["retrieval_hit_rate"],
                    mrr=metrics["mrr"],
                    workspace_accuracy=False if not route_matches else metrics["workspace_accuracy"],
                    citation_validity=metrics["citation_validity"],
                    citation_coverage=metrics["citation_coverage"],
                    refusal_accuracy=metrics["refusal_accuracy"],
                    tool_call_accuracy=metrics["tool_call_accuracy"],
                    latency_ms=latency_ms,
                    bad_case_types=bad_types or None,
                ))
                completed += 1

            except Exception as exc:
                await logger.awarning("eval_case_failed", case_id=case.case_id, error=str(exc))
                session.add(EvalResult(
                    run_id=eval_run_id,
                    case_id=case.id,
                    status="error",
                    error_message=str(exc)[:500],
                ))
                error_count += 1

            await session.commit()

        summary = {
            "total": total,
            "completed": completed,
            "errors": error_count,
            "eval_run_id": str(eval_run_id),
        }

        final_status = JobStatus.succeeded if error_count == 0 else JobStatus.failed
        await update_job_status(
            session, job_id, final_status, result_json=summary,
        )
        await session.commit()

    await logger.ainfo("eval_run_finished", **summary)
    return summary
