"""Prompt builder for final answer generation."""
from __future__ import annotations


def build_generator_messages(
    query: str,
    chunks: list[dict],
    tool_results: list[dict],
    route: str,
    error: str | None = None,
) -> list[dict]:
    evidence_lines: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        title = chunk.get("document_title", "")
        section = chunk.get("section_path", "")
        content = str(chunk.get("content", ""))
        evidence_lines.append(f"[{index}] {title} > {section}\n{content}")

    tool_lines: list[str] = []
    for result in tool_results:
        tool_lines.append(
            f"- {result.get('tool_name')}: status={result.get('status')} output={result.get('output')}"
        )

    system = (
        "You are DocWise, a developer knowledge assistant. Answer in the user's language. "
        "Use numbered citations like [1] only when they refer to supplied evidence chunks. "
        "When tool results are available, distinguish observed tool facts from document evidence."
    )
    user = (
        f"Route: {route}\n"
        f"Question: {query}\n\n"
        f"Evidence:\n{chr(10).join(evidence_lines) or '(none)'}\n\n"
        f"Tool results:\n{chr(10).join(tool_lines) or '(none)'}\n\n"
        f"Pipeline error: {error or '(none)'}\n\n"
        "Produce a structured, concise answer with conclusion, evidence, steps, and mitigation when relevant."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]

