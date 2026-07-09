from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.agent.rewriter.runtime import rewrite_query


@pytest.mark.asyncio
async def test_rewriter_always_sets_effective_query_on_llm_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.agent.rewriter.runtime.chat_completion", AsyncMock(side_effect=RuntimeError("boom")))

    result = await rewrite_query(
        original_query="Airflow scheduler timeout",
        route="troubleshooting",
        key_entities=[],
    )

    assert result.effective_query == "Airflow scheduler timeout"
    assert result.fallback_reason == "llm_error"


@pytest.mark.asyncio
async def test_rewriter_route_bypass_for_out_of_scope() -> None:
    result = await rewrite_query(
        original_query="帮我预测明天股票走势",
        route="out_of_scope",
        key_entities=[],
    )

    assert result.effective_query == "帮我预测明天股票走势"
    assert result.fallback_reason == "route_bypass"


@pytest.mark.asyncio
async def test_rewriter_too_short_falls_back_to_original(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.agent.rewriter.runtime.chat_completion", AsyncMock(return_value={"content": "ok"}))

    result = await rewrite_query(
        original_query="Airflow scheduler timeout troubleshooting",
        route="troubleshooting",
        key_entities=[],
    )

    assert result.effective_query == "Airflow scheduler timeout troubleshooting"
    assert result.fallback_reason == "too_short"


@pytest.mark.asyncio
async def test_rewriter_too_long_falls_back_to_truncated_original(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.agent.rewriter.runtime.chat_completion", AsyncMock(return_value={"content": "X" * 700}))

    result = await rewrite_query(
        original_query="Airflow scheduler timeout troubleshooting " * 20,
        route="troubleshooting",
        key_entities=[],
    )

    assert len(result.effective_query) == 512
    assert result.fallback_reason == "too_long"


@pytest.mark.asyncio
async def test_rewriter_missing_critical_entities_falls_back_to_original(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.agent.rewriter.runtime.chat_completion",
        AsyncMock(return_value={"content": "如何处理 Airflow DAG 连接重置错误"}),
    )

    result = await rewrite_query(
        original_query="如何处理 Airflow DAG ECONNRESET 错误",
        route="troubleshooting",
        key_entities=["Airflow"],
    )

    assert result.effective_query == "如何处理 Airflow DAG ECONNRESET 错误"
    assert result.fallback_reason == "missing_critical_entities"
    assert "ECONNRESET" in result.missing_entities


@pytest.mark.asyncio
async def test_rewriter_ignores_internal_workspace_slug_in_key_entities(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.agent.rewriter.runtime.chat_completion",
        AsyncMock(return_value={"content": "Airflow ECONNRESET 错误排查方法"}),
    )

    result = await rewrite_query(
        original_query="Airflow ECONNRESET 错误怎么排查？",
        route="troubleshooting",
        key_entities=["project_airflow"],
    )

    assert result.fallback_reason == ""
    assert result.effective_query == "Airflow ECONNRESET 错误排查方法"
    assert result.missing_entities == []


@pytest.mark.asyncio
async def test_rewriter_unchanged_passthrough_uses_original(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.agent.rewriter.runtime.chat_completion",
        AsyncMock(return_value={"content": "Airflow scheduler timeout"}),
    )

    result = await rewrite_query(
        original_query="Airflow scheduler timeout",
        route="troubleshooting",
        key_entities=[],
    )

    assert result.effective_query == "Airflow scheduler timeout"
    assert result.fallback_reason == "unchanged_passthrough"




# ---------------------------------------------------------------------------
# Hard-entity regex regression tests (BUG #H1 fix).
# Protect against re-introducing global re.IGNORECASE, which would degrade
# the error_code matcher into "any 3+ char ASCII word".
# ---------------------------------------------------------------------------


def test_entity_regex_does_not_match_lowercase_ascii_words() -> None:
    from src.agent.rewriter.entities import extract_regex_entities

    hits = extract_regex_entities("Airflow scheduler timeout troubleshooting")
    # "Airflow", "timeout", "troubleshooting" must NOT be captured as critical
    # entities (they are common English words, not uppercase error codes).
    assert "Airflow" not in hits
    assert "timeout" not in hits
    assert "troubleshooting" not in hits
    # "scheduler" must be captured by the component pattern.
    assert "scheduler" in hits


def test_entity_regex_preserves_uppercase_error_codes_and_pascal_names() -> None:
    from src.agent.rewriter.entities import extract_regex_entities

    hits = extract_regex_entities("如何处理 Airflow DAG ECONNRESET 错误 OOMKilled")
    assert "DAG" in hits
    assert "ECONNRESET" in hits
    assert "OOMKilled" in hits


def test_entity_regex_path_extracts_full_match_not_lowercase_fragments() -> None:
    from src.agent.rewriter.entities import extract_regex_entities

    hits = extract_regex_entities("check /etc/airflow.cfg for detail")
    assert "/etc/airflow.cfg" in hits
    # Before the fix, IGNORECASE over `[A-Z][A-Z0-9_]{2,}` would capture
    # "check", "etc", "airflow", "cfg", "detail" as critical entities.
    for noise in ("check", "etc", "airflow", "cfg", "detail"):
        assert noise not in hits


def test_entity_regex_component_matches_any_case() -> None:
    from src.agent.rewriter.entities import extract_regex_entities

    for variant in ("scheduler", "Scheduler", "SCHEDULER"):
        hits = extract_regex_entities(f"Airflow {variant} restarted")
        assert any(item.lower() == "scheduler" for item in hits), variant


@pytest.mark.asyncio
async def test_rewriter_en_to_zh_paraphrase_is_accepted_when_entities_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Before BUG #H1 fix, any EN→ZH paraphrase (the main rewriter use-case)
    # would be rejected with missing_critical_entities because every English
    # word in the original was treated as critical.
    monkeypatch.setattr(
        "src.agent.rewriter.runtime.chat_completion",
        AsyncMock(return_value={"content": "Airflow scheduler 超时排查步骤与常见原因"}),
    )

    result = await rewrite_query(
        original_query="Airflow scheduler timeout troubleshooting steps",
        route="troubleshooting",
        key_entities=[],
    )

    # scheduler is a critical component; it must survive (and it does).
    # timeout / troubleshooting are common English words, NOT critical,
    # so a ZH paraphrase that drops them must be accepted.
    assert result.fallback_reason == ""
    assert result.effective_query == "Airflow scheduler 超时排查步骤与常见原因"
