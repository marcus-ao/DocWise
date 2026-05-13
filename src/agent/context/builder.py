from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import structlog

from src.agent.context.compaction import summarize_overflow
from src.agent.context.formatters import (
    estimate_tokens,
    format_retrieval_item,
    format_tool_result_item,
    safe_budget,
    shorten_preview,
)
from src.agent.context.types import ContextDiagnostics, ModelContext, SectionPreview
from src.agent.prompts.generator import GENERATOR_SYSTEM_PROMPT, compose_generator_user_prompt
from src.agent.prompts.tool_planner import TOOL_PLANNER_SYSTEM, compose_tool_planner_user_prompt
from src.agent.state import AgentState
from src.config.settings import settings

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class _SectionItem:
    key: str
    section_kind: Literal["retrieval", "tool_result"]
    text: str
    before_chars: int
    after_chars: int
    token_estimate: int
    score: float | None = None


async def build_answer_context(
    state: AgentState,
    *,
    recent_turns: list[dict] | None = None,
    context_summary: str | None = None,
    budget_override: int | None = None,
) -> ModelContext:
    budget = int(budget_override or settings.answer_context_budget)
    query_identity = _query_identity(state)
    route = str(state.get("route") or "tech_general")
    error = state.get("error")
    retrieval_items = _build_retrieval_items(
        state.get("reranked_chunks") or [],
        include_content=True,
        max_chars=settings.context_max_chunk_chars,
    )
    tool_items = _build_tool_items(
        state.get("tool_results") or [],
        max_chars=settings.context_max_tool_result_chars,
    )

    system_text = GENERATOR_SYSTEM_PROMPT
    return await _build_model_context(
        budget=budget,
        system_text=system_text,
        query_identity=query_identity,
        route=route,
        retrieval_items=retrieval_items,
        tool_items=tool_items,
        compose_message=lambda retrieval_lines, tool_lines, summary: compose_generator_user_prompt(
            query=query_identity,
            route=route,
            evidence_lines=retrieval_lines,
            tool_lines=tool_lines,
            error=error,
            recent_turns=recent_turns,
            context_summary=context_summary,
            compaction_summary=summary,
        ),
    )


async def build_tool_planner_context(
    state: AgentState,
    *,
    recent_turns: list[dict] | None = None,
    context_summary: str | None = None,
    budget_override: int | None = None,
) -> ModelContext:
    budget = int(budget_override or settings.tool_planner_context_budget)
    query_identity = _query_identity(state)
    route = str(state.get("route") or "tech_general")
    retrieval_items = _build_retrieval_items(
        state.get("reranked_chunks") or [],
        include_content=False,
        max_chars=settings.context_max_chunk_chars,
    )
    tool_items = _build_failed_tool_items(
        state.get("tool_results") or [],
        max_chars=settings.context_max_tool_result_chars,
    )
    tools_to_plan = [str(item) for item in state.get("tools_to_call") or []]

    return await _build_model_context(
        budget=budget,
        system_text=TOOL_PLANNER_SYSTEM,
        query_identity=query_identity,
        route=route,
        retrieval_items=retrieval_items,
        tool_items=tool_items,
        compose_message=lambda retrieval_lines, tool_lines, summary: compose_tool_planner_user_prompt(
            query=query_identity,
            key_entities=[str(item) for item in state.get("key_entities") or []],
            selected_project=state.get("selected_project"),
            tools_to_plan=tools_to_plan,
            retrieval_lines=retrieval_lines,
            recent_tool_failures=tool_lines,
            recent_turns=recent_turns,
            context_summary=context_summary,
            route=route,
            compaction_summary=summary,
        ),
    )


async def _build_model_context(
    *,
    budget: int,
    system_text: str,
    query_identity: str,
    route: str,
    retrieval_items: list[_SectionItem],
    tool_items: list[_SectionItem],
    compose_message,
) -> ModelContext:
    safe_limit = safe_budget(budget)
    truncations: list[tuple[str, int]] = []
    kept_retrieval = list(retrieval_items)
    kept_tools = list(tool_items)
    overflow_for_summary: list[str] = []
    compaction_summary: str | None = None
    compaction_triggered = False
    compaction_input_tokens: int | None = None
    compaction_output_tokens: int | None = None

    working_query = compose_message(
        [item.text for item in kept_retrieval],
        [item.text for item in kept_tools],
        None,
    )
    total_tokens = _message_tokens(system_text, working_query)

    if total_tokens > safe_limit:
        kept_tools, tool_overflow, tool_truncations = _shrink_tool_items(
            kept_tools,
            safe_limit,
            system_text,
            kept_retrieval,
            compose_message,
        )
        truncations.extend(tool_truncations)
        overflow_for_summary.extend(f"[tool_result] {item}" for item in tool_overflow)

    working_query = compose_message(
        [item.text for item in kept_retrieval],
        [item.text for item in kept_tools],
        None,
    )
    total_tokens = _message_tokens(system_text, working_query)
    if total_tokens > safe_limit:
        kept_retrieval, retrieval_overflow, retrieval_truncations = _drop_low_score_retrieval(
            kept_retrieval,
            safe_limit,
            system_text,
            kept_tools,
            compose_message,
        )
        truncations.extend(retrieval_truncations)
        overflow_for_summary.extend(f"[retrieval] {item}" for item in retrieval_overflow)

    working_query = compose_message(
        [item.text for item in kept_retrieval],
        [item.text for item in kept_tools],
        None,
    )
    total_tokens = _message_tokens(system_text, working_query)
    if total_tokens > safe_limit:
        compaction_triggered = True
        while total_tokens > safe_limit and kept_tools:
            removed = kept_tools.pop()
            overflow_for_summary.append(f"[tool_result] {removed.text}")
            truncations.append((removed.key, removed.after_chars))  # chars dropped = full item removed
            working_query = compose_message(
                [item.text for item in kept_retrieval],
                [item.text for item in kept_tools],
                None,
            )
            total_tokens = _message_tokens(system_text, working_query)
        while total_tokens > safe_limit and kept_retrieval:
            removed = kept_retrieval.pop()
            overflow_for_summary.append(f"[retrieval] {removed.text}")
            truncations.append((removed.key, removed.after_chars))  # chars dropped = full item removed
            working_query = compose_message(
                [item.text for item in kept_retrieval],
                [item.text for item in kept_tools],
                None,
            )
            total_tokens = _message_tokens(system_text, working_query)

        if overflow_for_summary:
            try:
                summary, in_tokens, out_tokens = await summarize_overflow(
                    query=query_identity,
                    route=route,
                    overflow_sections=overflow_for_summary,
                )
                compaction_summary = summary
                compaction_input_tokens = in_tokens
                compaction_output_tokens = out_tokens
            except Exception as exc:  # noqa: BLE001 - LLM compaction failed; hard-truncate will run below if still over budget.
                logger.warning("context_compaction_failed", error=str(exc), route=route)
                compaction_summary = None

    working_query = compose_message(
        [item.text for item in kept_retrieval],
        [item.text for item in kept_tools],
        compaction_summary,
    )
    estimated_prompt_tokens = _message_tokens(system_text, working_query)
    if estimated_prompt_tokens > safe_limit:
        working_query = _hard_truncate_prompt(working_query, safe_limit - estimate_tokens(system_text))
        estimated_prompt_tokens = _message_tokens(system_text, working_query)

    sections = _build_sections(
        system_text=system_text,
        query_identity=query_identity,
        retrieval_items=kept_retrieval,
        tool_items=kept_tools,
        compaction_summary=compaction_summary,
    )
    diagnostics: ContextDiagnostics = {
        "budget": budget,
        "estimated_prompt_tokens": estimated_prompt_tokens,
        "sections": sections,
        "truncations": truncations,
        "compaction_triggered": compaction_triggered,
        "compaction_input_tokens": compaction_input_tokens,
        "compaction_output_tokens": compaction_output_tokens,
        "fallback_used": False,
        "fallback_reason": None,
    }
    return ModelContext(
        messages=[
            {"role": "system", "content": system_text},
            {"role": "user", "content": working_query},
        ],
        diagnostics=diagnostics,
        preview=sections,
        estimated_prompt_tokens=estimated_prompt_tokens,
        compaction_summary=compaction_summary,
    )


def _build_retrieval_items(chunks: list[dict], *, include_content: bool, max_chars: int) -> list[_SectionItem]:
    items: list[_SectionItem] = []
    for index, chunk in enumerate(chunks, start=1):
        text, dropped = format_retrieval_item(chunk, include_content=include_content, max_chars=max_chars)
        items.append(
            _SectionItem(
                key=f"retrieval:{index}",
                section_kind="retrieval",
                text=text,
                before_chars=len(str(chunk.get("content") or "")) if include_content else len(text),
                after_chars=len(text),
                token_estimate=estimate_tokens(text),
                score=_score(chunk.get("rerank_score")),
            )
        )
        if dropped > 0:
            items[-1].before_chars = items[-1].after_chars + dropped
    return items


def _build_tool_items(results: list[dict], *, max_chars: int) -> list[_SectionItem]:
    items: list[_SectionItem] = []
    for index, result in enumerate(results, start=1):
        text, dropped = format_tool_result_item(result, max_chars=max_chars)
        payload = result.get("error") or result.get("output") or ""
        items.append(
            _SectionItem(
                key=f"tool_result:{index}",
                section_kind="tool_result",
                text=text,
                before_chars=len(str(payload)),
                after_chars=len(text),
                token_estimate=estimate_tokens(text),
            )
        )
        if dropped > 0:
            items[-1].before_chars = items[-1].after_chars + dropped
    return items


def _build_failed_tool_items(results: list[dict], *, max_chars: int) -> list[_SectionItem]:
    failed = [result for result in results if result.get("error") or str(result.get("status") or "").lower() not in {"success", "succeeded"}]
    return _build_tool_items(failed[-settings.context_max_failed_tools :], max_chars=max_chars)


def _shrink_tool_items(
    items: list[_SectionItem],
    safe_limit: int,
    system_text: str,
    retrieval_items: list[_SectionItem],
    compose_message,
) -> tuple[list[_SectionItem], list[str], list[tuple[str, int]]]:
    kept = list(items)
    overflow: list[str] = []
    truncations: list[tuple[str, int]] = []
    min_chars = settings.context_min_tool_chars
    for index in range(len(kept) - 1, -1, -1):
        current = kept[index]
        query_text = compose_message(
            [item.text for item in retrieval_items],
            [item.text for item in kept],
            None,
        )
        if _message_tokens(system_text, query_text) <= safe_limit:
            break
        if current.after_chars <= min_chars:
            overflow.append(current.text)
            truncations.append((current.key, current.after_chars))
            kept.pop(index)
            continue
        trimmed_text = current.text[:min_chars]
        dropped = current.after_chars - len(trimmed_text)
        kept[index] = _SectionItem(
            key=current.key,
            section_kind=current.section_kind,
            text=trimmed_text,
            before_chars=current.before_chars,
            after_chars=len(trimmed_text),
            token_estimate=estimate_tokens(trimmed_text),
            score=current.score,
        )
        overflow.append(current.text[len(trimmed_text) :].strip())
        truncations.append((current.key, dropped))
    return kept, [item for item in overflow if item], truncations


def _drop_low_score_retrieval(
    items: list[_SectionItem],
    safe_limit: int,
    system_text: str,
    tool_items: list[_SectionItem],
    compose_message,
) -> tuple[list[_SectionItem], list[str], list[tuple[str, int]]]:
    kept = list(items)
    overflow: list[str] = []
    truncations: list[tuple[str, int]] = []
    index = len(kept) - 1
    while index >= 0:
        query_text = compose_message(
            [item.text for item in kept],
            [item.text for item in tool_items],
            None,
        )
        if _message_tokens(system_text, query_text) <= safe_limit:
            break
        current = kept[index]
        if current.score is not None and current.score >= settings.context_min_retrieval_score:
            index -= 1
            continue
        overflow.append(current.text)
        truncations.append((current.key, current.after_chars))
        kept.pop(index)
        index -= 1
    return kept, overflow, truncations


def _build_sections(
    *,
    system_text: str,
    query_identity: str,
    retrieval_items: list[_SectionItem],
    tool_items: list[_SectionItem],
    compaction_summary: str | None,
) -> dict[str, SectionPreview]:
    sections: dict[str, SectionPreview] = {
        "system": _section_preview("system", [system_text], [system_text]),
        "query": _section_preview("query", [query_identity], [query_identity]),
        "retrieval": _section_preview_items("retrieval", retrieval_items),
        "tool_result": _section_preview_items("tool_result", tool_items),
    }
    if compaction_summary:
        sections["summary"] = _section_preview("summary", [compaction_summary], [compaction_summary])
    return sections


def _section_preview(
    section_kind: Literal["system", "query", "retrieval", "tool_result", "summary"],
    before_items: list[str],
    after_items: list[str],
) -> SectionPreview:
    after_text = "\n".join(after_items)
    return {
        "section_kind": section_kind,
        "item_count": len(after_items),
        "total_chars_before": sum(len(item) for item in before_items),
        "total_chars_after": sum(len(item) for item in after_items),
        "token_estimate": estimate_tokens(after_text) if after_text else 0,
        "items_preview": [shorten_preview(item) for item in after_items[:5]],
    }


def _section_preview_items(
    section_kind: Literal["retrieval", "tool_result"],
    items: list[_SectionItem],
) -> SectionPreview:
    return {
        "section_kind": section_kind,
        "item_count": len(items),
        "total_chars_before": sum(item.before_chars for item in items),
        "total_chars_after": sum(item.after_chars for item in items),
        "token_estimate": sum(item.token_estimate for item in items),
        "items_preview": [shorten_preview(item.text) for item in items[:5]],
    }


def _message_tokens(system_text: str, query_text: str) -> int:
    return estimate_tokens(system_text) + estimate_tokens(query_text)


def _query_identity(state: AgentState) -> str:
    return str(
        state.get("effective_query")
        or state.get("rewritten_query")
        or state.get("original_query")
        or ""
    )


def _score(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _hard_truncate_prompt(query_text: str, remaining_tokens: int) -> str:
    if remaining_tokens <= 0:
        return ""
    if estimate_tokens(query_text) <= remaining_tokens:
        return query_text
    chars = max(
        settings.context_hard_truncate_min_chars,
        int(len(query_text) * settings.context_hard_truncate_initial_ratio),
    )
    trimmed = query_text
    while estimate_tokens(trimmed) > remaining_tokens and chars > settings.context_hard_truncate_floor_chars:
        trimmed = trimmed[:chars]
        chars = int(chars * settings.context_hard_truncate_step_ratio)
    return trimmed
