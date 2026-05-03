"""arq job entrypoints for document pipeline work."""
from __future__ import annotations

from src.document.ingestion import ingest_document_by_job_id, reindex_document_by_job_id


async def process_ingest_document(ctx: dict, job_id: str) -> dict:
    return await ingest_document_by_job_id(job_id)


async def process_reindex(ctx: dict, job_id: str) -> dict:
    return await reindex_document_by_job_id(job_id)


async def process_eval_run(ctx: dict, job_id: str) -> dict:
    from src.observability.evaluator import run_eval

    return await run_eval(job_id=job_id)
