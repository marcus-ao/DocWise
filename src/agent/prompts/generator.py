"""Prompt builder for final answer generation."""
from __future__ import annotations

GENERATOR_SYSTEM_PROMPT = (
    "You are DocWise, a developer knowledge assistant. Answer in the user's language. "
    "Use numbered citations like [1] only when they refer to supplied evidence chunks. "
    "When tool results are available, distinguish observed tool facts from document evidence."
)


def compose_generator_user_prompt(
    *,
    query: str,
    route: str,
    evidence_lines: list[str],
    tool_lines: list[str],
    error: str | None = None,
    recent_turns: list[dict] | None = None,
    context_summary: str | None = None,
    compaction_summary: str | None = None,
) -> str:
    turns_block = ""
    if recent_turns:
        rendered_turns: list[str] = []
        for turn in recent_turns:
            user_query = str(turn.get("query") or turn.get("user") or "").strip()
            answer = str(turn.get("answer") or turn.get("assistant") or "").strip()
            tool_facts = turn.get("tool_facts") or []
            if user_query:
                rendered_turns.append(f"User: {user_query}")
            if answer:
                rendered_turns.append(f"Assistant: {answer}")
            if tool_facts:
                rendered_turns.append(f"Tool facts: {'; '.join(str(item) for item in tool_facts)}")
        if rendered_turns:
            turns_block = f"Recent turns:\n{chr(10).join(rendered_turns)}\n\n"

    summary_block = f"Context summary:\n{context_summary}\n\n" if context_summary else ""
    compaction_block = f"Compacted overflow facts:\n{compaction_summary}\n\n" if compaction_summary else ""
    return (
        f"Route: {route}\n"
        f"Question: {query}\n\n"
        f"{turns_block}"
        f"{summary_block}"
        f"Evidence:\n{chr(10).join(evidence_lines) or '(none)'}\n\n"
        f"Tool results:\n{chr(10).join(tool_lines) or '(none)'}\n\n"
        f"{compaction_block}"
        f"Pipeline error: {error or '(none)'}\n\n"
        "Produce a structured, concise answer with conclusion, evidence, steps, and mitigation when relevant."
    )


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

    user = compose_generator_user_prompt(
        query=query,
        route=route,
        evidence_lines=evidence_lines,
        tool_lines=tool_lines,
        error=error,
    )
    return [{"role": "system", "content": GENERATOR_SYSTEM_PROMPT}, {"role": "user", "content": user}]
