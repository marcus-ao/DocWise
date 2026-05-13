from __future__ import annotations

from src.agent.prompts.rewriter import build_rewriter_messages
from src.agent.rewriter.cleaner import clean_rewriter_output, normalize_for_compare, normalize_spaces
from src.agent.rewriter.entities import merge_critical_entities, missing_critical_entities
from src.agent.rewriter.result import RewriterResult
from src.config.settings import settings
from src.llm.client import chat_completion


async def rewrite_query(
    *,
    original_query: str,
    route: str,
    key_entities: list[str] | None = None,
    recent_turns: list[dict] | None = None,
    context_summary: str | None = None,
    use_history: bool | None = None,
) -> RewriterResult:
    base_original = normalize_spaces(original_query)
    history_enabled = settings.rewriter_use_history if use_history is None else bool(use_history)
    history_used = bool(history_enabled and (recent_turns or context_summary))

    if route == "out_of_scope":
        return _result(
            original=base_original,
            rewritten=base_original,
            effective=base_original,
            route=route,
            history_used=history_used,
            fallback_reason="route_bypass",
        )

    try:
        response = await chat_completion(
            build_rewriter_messages(
                base_original,
                route,
                recent_turns=recent_turns,
                context_summary=context_summary,
                use_history=history_enabled,
            ),
            model="fast",
            temperature=0,
            timeout=15.0,
        )
    except Exception:
        return _result(
            original=base_original,
            rewritten=base_original,
            effective=base_original,
            route=route,
            history_used=history_used,
            fallback_reason="llm_error",
        )

    rewritten = clean_rewriter_output(str(response.get("content") or ""))
    if not rewritten:
        return _result(
            original=base_original,
            rewritten="",
            effective=base_original,
            route=route,
            history_used=history_used,
            fallback_reason="empty_output",
        )

    if len(rewritten) < settings.rewriter_min_effective_query_chars and len(base_original) >= settings.rewriter_min_effective_query_chars:
        return _result(
            original=base_original,
            rewritten=rewritten,
            effective=base_original,
            route=route,
            history_used=history_used,
            fallback_reason="too_short",
        )

    if len(rewritten) > settings.rewriter_effective_query_max_chars:
        return _result(
            original=base_original,
            rewritten=rewritten,
            effective=base_original[: settings.rewriter_effective_query_max_chars],
            route=route,
            history_used=history_used,
            fallback_reason="too_long",
        )

    if normalize_for_compare(rewritten) == normalize_for_compare(base_original):
        return _result(
            original=base_original,
            rewritten=rewritten,
            effective=base_original,
            route=route,
            history_used=history_used,
            fallback_reason="unchanged_passthrough",
        )

    critical_entities = merge_critical_entities(
        base_original,
        list(key_entities or []),
    )
    missing_entities = missing_critical_entities(rewritten, critical_entities)
    if missing_entities:
        return _result(
            original=base_original,
            rewritten=rewritten,
            effective=base_original,
            route=route,
            history_used=history_used,
            fallback_reason="missing_critical_entities",
            missing_entities=missing_entities,
        )

    return _result(
        original=base_original,
        rewritten=rewritten,
        effective=rewritten,
        route=route,
        history_used=history_used,
        fallback_reason="",
    )


def _result(
    *,
    original: str,
    rewritten: str,
    effective: str,
    route: str,
    history_used: bool,
    fallback_reason: str,
    missing_entities: list[str] | None = None,
) -> RewriterResult:
    return RewriterResult(
        original_query=original,
        rewritten_query=rewritten,
        effective_query=effective,
        route=route,
        history_used=history_used,
        fallback_reason=fallback_reason,
        missing_entities=list(missing_entities or []),
        diagnostic_hint=_diagnostic_hint(fallback_reason, list(missing_entities or [])),
    )


def _diagnostic_hint(fallback_reason: str, missing_entities: list[str]) -> str | None:
    if fallback_reason == "unchanged_passthrough":
        return "LLM 输出与原 query 等价，rewrite 未生效。"
    if fallback_reason == "missing_critical_entities":
        joined = ", ".join(missing_entities)
        return f"改写丢失关键实体 [{joined}]，已回退。"
    if fallback_reason == "empty_output":
        return "LLM 返回空结果，已回退到原 query。"
    if fallback_reason == "too_short":
        return "改写结果过短，已回退到原 query。"
    if fallback_reason == "too_long":
        return "改写结果过长，已回退到截断后的原 query。"
    if fallback_reason == "llm_error":
        return "LLM 改写失败，已回退到原 query。"
    if fallback_reason == "route_bypass":
        return "当前路由跳过 rewrite。"
    return None
