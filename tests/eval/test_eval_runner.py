"""Tests for observability: tracer imports, metrics, bad_case, evaluator."""
from __future__ import annotations

import pytest

from scripts.seed_eval_cases import load_eval_cases, upsert_eval_cases
from src.models.base import RouteType
from src.observability.bad_case import classify_bad_cases
from src.observability.evaluator import _expected_workspace_slugs
from src.observability.metrics import (
    citation_coverage,
    citation_validity,
    hit_rate_at_k,
    latency_percentile,
    mrr_at_k,
    refusal_accuracy,
    tool_call_accuracy,
    uid_matches,
    workspace_accuracy,
)

# ============================================================
# Tracer import verification
# ============================================================


class TestTracerImport:
    def test_tracer_functions_importable(self):
        from src.observability.tracer import (
            complete_agent_run,
            create_agent_run,
            write_retrieval_result,
            write_tool_call,
            write_trace_event,
        )
        assert callable(write_trace_event)
        assert callable(write_retrieval_result)
        assert callable(write_tool_call)
        assert callable(create_agent_run)
        assert callable(complete_agent_run)

    def test_tracer_importable_from_package(self):
        from src.observability import (  # noqa: F401
            complete_agent_run,
            create_agent_run,
            write_retrieval_result,
            write_tool_call,
            write_trace_event,
        )
        assert callable(write_trace_event)

# ============================================================
# Metrics: uid_matches
# ============================================================


class TestUidMatches:
    def test_exact_match(self):
        assert uid_matches("airflow-docs:scheduling:abc123", "airflow-docs:scheduling:abc123")

    def test_exact_no_match(self):
        assert not uid_matches("airflow-docs:scheduling:abc123", "airflow-docs:scheduling:xyz789")

    def test_wildcard_match(self):
        assert uid_matches("airflow-docs:scheduling:*", "airflow-docs:scheduling:abc123")

    def test_wildcard_no_match(self):
        assert not uid_matches("airflow-docs:scheduling:*", "backstage-docs:catalog:abc123")

    def test_wildcard_empty_suffix(self):
        assert uid_matches("prefix:*", "prefix:")


# ============================================================
# Metrics: hit_rate_at_k
# ============================================================


class TestHitRateAtK:
    def test_all_hit(self):
        expected = ["a", "b"]
        actual = ["a", "b", "c", "d", "e"]
        assert hit_rate_at_k(expected, actual, k=5) == 1.0

    def test_none_hit(self):
        expected = ["x", "y"]
        actual = ["a", "b", "c", "d", "e"]
        assert hit_rate_at_k(expected, actual, k=5) == 0.0

    def test_partial_hit(self):
        expected = ["a", "x"]
        actual = ["a", "b", "c", "d", "e"]
        assert hit_rate_at_k(expected, actual, k=5) == 0.5

    def test_empty_expected(self):
        assert hit_rate_at_k([], ["a", "b"], k=5) == 0.0

    def test_wildcard_hit(self):
        expected = ["airflow-docs:*"]
        actual = ["airflow-docs:scheduling:abc"]
        assert hit_rate_at_k(expected, actual, k=5) == 1.0

    def test_k_limits_search(self):
        expected = ["z"]
        actual = ["a", "b", "c", "d", "e", "z"]
        assert hit_rate_at_k(expected, actual, k=5) == 0.0


# ============================================================
# Metrics: mrr_at_k
# ============================================================


class TestMrrAtK:
    def test_first_position(self):
        assert mrr_at_k(["a"], ["a", "b", "c"], k=5) == 1.0

    def test_second_position(self):
        assert mrr_at_k(["b"], ["a", "b", "c"], k=5) == 0.5

    def test_no_hit(self):
        assert mrr_at_k(["x"], ["a", "b", "c"], k=5) == 0.0

    def test_empty_expected(self):
        assert mrr_at_k([], ["a", "b"], k=5) == 0.0


# ============================================================
# Metrics: workspace_accuracy
# ============================================================


class TestWorkspaceAccuracy:
    def test_subset(self):
        assert workspace_accuracy(["a"], ["a", "b"]) is True

    def test_exact_match(self):
        assert workspace_accuracy(["a", "b"], ["a", "b"]) is True

    def test_not_subset(self):
        assert workspace_accuracy(["a", "c"], ["a", "b"]) is False

    def test_empty_expected(self):
        assert workspace_accuracy([], ["a", "b"]) is True


# ============================================================
# Metrics: citation_validity and coverage
# ============================================================


class TestCitationMetrics:
    def test_validity_all_valid(self):
        assert citation_validity(["a", "b"], ["a", "b", "c"]) == 1.0

    def test_validity_partial(self):
        assert citation_validity(["a", "x"], ["a", "b"]) == 0.5

    def test_validity_empty_actual(self):
        assert citation_validity([], ["a"]) == 1.0

    def test_coverage_all_covered(self):
        assert citation_coverage(["a", "b"], ["a", "b", "c"]) == 1.0

    def test_coverage_partial(self):
        assert citation_coverage(["a", "x"], ["a", "b"]) == 0.5

    def test_coverage_wildcard(self):
        assert citation_coverage(["prefix:*"], ["prefix:abc"]) == 1.0

    def test_coverage_empty_expected(self):
        assert citation_coverage([], ["a"]) == 1.0


# ============================================================
# Metrics: refusal_accuracy and tool_call_accuracy
# ============================================================


class TestOtherMetrics:
    def test_refusal_match(self):
        assert refusal_accuracy(True, True) is True
        assert refusal_accuracy(False, False) is True

    def test_refusal_mismatch(self):
        assert refusal_accuracy(True, False) is False
        assert refusal_accuracy(False, True) is False

    def test_tool_accuracy_exact(self):
        assert tool_call_accuracy(["a", "b"], ["a", "b"]) == 1.0

    def test_tool_accuracy_partial(self):
        assert tool_call_accuracy(["a", "b"], ["a", "c"]) == pytest.approx(1 / 3)

    def test_tool_accuracy_both_empty(self):
        assert tool_call_accuracy([], []) == 1.0

    def test_latency_percentile_basic(self):
        assert latency_percentile([100, 200, 300, 400, 500], 50.0) == 300

    def test_latency_percentile_empty(self):
        assert latency_percentile([], 95.0) is None


# ============================================================
# Bad case classifier
# ============================================================


class TestBadCaseClassifier:
    def test_no_bad_cases(self):
        case = {"should_refuse": False}
        result = {
            "retrieval_hit_rate": 1.0,
            "workspace_accuracy": True,
            "citation_validity": 1.0,
            "citation_coverage": 0.8,
            "refusal_accuracy": True,
            "tool_call_accuracy": 1.0,
            "answer_correctness": 0.9,
            "latency_ms": 3000,
        }
        assert classify_bad_cases(case, result) == []

    def test_retrieval_miss(self):
        case = {"should_refuse": False}
        result = {"retrieval_hit_rate": 0.5}
        types = classify_bad_cases(case, result)
        assert "retrieval_miss" in types

    def test_wrong_workspace(self):
        case = {"should_refuse": False}
        result = {"workspace_accuracy": False}
        types = classify_bad_cases(case, result)
        assert "wrong_workspace" in types

    def test_wrong_refusal(self):
        case = {"should_refuse": False}
        result = {"refusal_accuracy": False}
        types = classify_bad_cases(case, result)
        assert "wrong_refusal" in types

    def test_missed_refusal(self):
        case = {"should_refuse": True}
        result = {"refusal_accuracy": False}
        types = classify_bad_cases(case, result)
        assert "missed_refusal" in types

    def test_tool_failure(self):
        case = {"should_refuse": False}
        result = {}
        tool_calls = [{"tool_name": "search", "status": "error"}]
        types = classify_bad_cases(case, result, tool_calls)
        assert "tool_failure" in types

    def test_latency_high(self):
        case = {"should_refuse": False}
        result = {"latency_ms": 9000}
        types = classify_bad_cases(case, result)
        assert "latency_high" in types

    def test_low_answer_score(self):
        case = {"should_refuse": False}
        result = {"answer_correctness": 0.4}
        types = classify_bad_cases(case, result)
        assert "low_answer_score" in types


class TestEvaluatorHelpers:
    def test_expected_workspace_slugs_for_project_route(self):
        class Case:
            workspace_slug = "project_airflow"

            class route:
                value = "project_specific"

        assert _expected_workspace_slugs(Case()) == ["project_airflow", "public_tech"]

    def test_expected_workspace_slugs_for_troubleshooting_includes_public(self):
        class Case:
            workspace_slug = "project_airflow"

            class route:
                value = "troubleshooting"

        assert _expected_workspace_slugs(Case()) == ["project_airflow", "public_tech"]

    def test_expected_workspace_slugs_for_general_route(self):
        class Case:
            workspace_slug = None

            class route:
                value = "tech_general"

        assert _expected_workspace_slugs(Case()) == ["public_tech"]


class TestSeedEvalCases:
    def test_load_eval_cases_reads_both_jsonl_files(self, tmp_path):
        eval_dir = tmp_path / "eval"
        eval_dir.mkdir()
        (eval_dir / "retrieval_golden.jsonl").write_text(
            '{"case_id":"ret_1","query":"q","route":"tech_general"}\n',
            encoding="utf-8",
        )
        (eval_dir / "qa_pairs.jsonl").write_text(
            '{"case_id":"qa_1","query":"q","route":"out_of_scope","should_refuse":true}\n',
            encoding="utf-8",
        )

        cases = load_eval_cases(eval_dir)

        assert [case["case_id"] for case in cases] == ["ret_1", "qa_1"]

    async def test_upsert_eval_cases_is_idempotent(self):
        added: list[object] = []
        existing_by_case_id: dict[str, object] = {}

        class FakeResult:
            def __init__(self, value: object | None) -> None:
                self.value = value

        class FakeSession:
            async def scalar(self, stmt: object) -> object | None:
                return existing_by_case_id.get("case-1")

            def add(self, item: object) -> None:
                added.append(item)
                existing_by_case_id["case-1"] = item

            async def commit(self) -> None:
                return None

        raw = [{"case_id": "case-1", "query": "q1", "route": "tech_general"}]

        inserted, updated = await upsert_eval_cases(FakeSession(), raw)
        raw[0]["query"] = "q2"
        inserted_again, updated_again = await upsert_eval_cases(FakeSession(), raw)

        assert (inserted, updated) == (1, 0)
        assert (inserted_again, updated_again) == (0, 1)
        assert added[0].query == "q2"
        assert added[0].route == RouteType.tech_general
