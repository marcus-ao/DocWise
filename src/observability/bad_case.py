"""Bad case classifier — 10 types per eval_case_format.md contract."""
from __future__ import annotations

from src.models.base import BadCaseType


def classify_bad_cases(
    eval_case: dict,
    eval_result: dict,
    tool_calls: list[dict] | None = None,
) -> list[str]:
    """Return list of BadCaseType values for this eval result. May be empty."""
    types: list[str] = []

    hit_rate = eval_result.get("retrieval_hit_rate")
    if hit_rate is not None and hit_rate < 1.0:
        types.append(BadCaseType.retrieval_miss.value)

    ws_acc = eval_result.get("workspace_accuracy")
    if ws_acc is False:
        types.append(BadCaseType.wrong_workspace.value)

    cit_val = eval_result.get("citation_validity")
    if cit_val is not None and cit_val < 1.0:
        types.append(BadCaseType.bad_citation.value)

    cit_cov = eval_result.get("citation_coverage")
    if cit_cov is not None and cit_cov < 0.5:
        types.append(BadCaseType.missing_citation.value)

    should_refuse = eval_case.get("should_refuse", False)
    refusal_acc = eval_result.get("refusal_accuracy")
    if refusal_acc is False:
        if should_refuse:
            types.append(BadCaseType.missed_refusal.value)
        else:
            types.append(BadCaseType.wrong_refusal.value)

    tool_acc = eval_result.get("tool_call_accuracy")
    if tool_acc is not None and tool_acc < 1.0:
        types.append(BadCaseType.wrong_tool_call.value)

    if tool_calls:
        if any(tc.get("status") == "error" for tc in tool_calls):
            types.append(BadCaseType.tool_failure.value)

    answer_score = eval_result.get("answer_correctness")
    if answer_score is not None and answer_score < 0.6:
        types.append(BadCaseType.low_answer_score.value)

    latency = eval_result.get("latency_ms")
    if latency is not None and latency > 8000:
        types.append(BadCaseType.latency_high.value)

    return types
