"""Generate a lightweight runbook draft from retrieved evidence and tool output."""
from __future__ import annotations

from src.agent.tools.schemas import RunbookCitation, RunbookDraftOutput


async def generate_runbook_draft(
    title: str | None = None,
    severity: str = "warning",
    query: str | None = None,
    chunks: list[dict] | None = None,
    tool_results: list[dict] | None = None,
) -> dict:
    citations = [
        RunbookCitation(
            chunk_uid=str(chunk.get("chunk_uid", "")),
            document_title=str(chunk.get("document_title", "")),
            section_path=chunk.get("section_path"),
            quote=str(chunk.get("content", ""))[:500],
        )
        for chunk in (chunks or [])[:3]
    ]
    return RunbookDraftOutput(
        title=title or f"Runbook: {query or 'Operational Incident'}",
        severity=severity,
        symptoms=["Service is unhealthy or user-reported failure is present."],
        diagnosis_steps=[
            "Check service status and active alerts.",
            "Review recent ERROR logs for the affected service.",
            "Compare findings with the cited runbook evidence.",
        ],
        mitigation_steps=[
            "Apply the relevant restart, rollback, or scaling action from the runbook.",
            "Monitor health checks and error rate after the change.",
        ],
        rollback_steps=["Revert the last risky change if mitigation worsens service health."],
        citations=citations,
    ).model_dump()

