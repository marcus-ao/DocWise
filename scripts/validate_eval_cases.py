"""Validate eval case JSONL files against eval_case_format.md contract."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
EVAL_DIR = BASE_DIR / "data" / "eval"

VALID_ROUTES = {"tech_general", "project_specific", "troubleshooting", "runbook_generation", "out_of_scope"}
VALID_WORKSPACES = {"public_tech", "project_airflow", "project_backstage", "project_fastapi", "mock_ops"}
CHUNK_INDEX_PATH = BASE_DIR / "data" / "processed" / "chunk_index.csv"

errors: list[str] = []


def load_chunk_index() -> set[str] | None:
    if not CHUNK_INDEX_PATH.exists():
        return None
    with open(CHUNK_INDEX_PATH, newline="", encoding="utf-8") as f:
        return {row["chunk_uid"] for row in csv.DictReader(f) if row.get("chunk_uid")}


def validate_chunk_uid_refs(file_name: str, case: dict, chunk_index: set[str] | None) -> None:
    if chunk_index is None:
        return
    cid = case.get("case_id", "")
    for field in ("expected_chunk_uids", "expected_citations"):
        for uid in case.get(field, []):
            if uid.endswith("*"):
                prefix = uid[:-1]
                if not any(actual.startswith(prefix) for actual in chunk_index):
                    errors.append(f"{file_name}: {cid} {field} prefix not found: {uid}")
            elif uid not in chunk_index:
                errors.append(f"{file_name}: {cid} {field} uid not found: {uid}")


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        errors.append(f"MISSING: {path}")
        return []
    cases = []
    for i, line in enumerate(path.read_text(encoding="utf-8").strip().splitlines(), 1):
        try:
            cases.append(json.loads(line))
        except json.JSONDecodeError as exc:
            errors.append(f"{path.name}:{i}: invalid JSON: {exc}")
    return cases


def validate_retrieval_golden(cases: list[dict], chunk_index: set[str] | None) -> None:
    if len(cases) < 20:
        errors.append(f"retrieval_golden.jsonl: only {len(cases)} cases, expected >=20")

    ids = set()
    for c in cases:
        cid = c.get("case_id", "")
        if not cid.startswith("ret_"):
            errors.append(f"retrieval_golden.jsonl: case_id={cid} missing ret_ prefix")
        if cid in ids:
            errors.append(f"retrieval_golden.jsonl: duplicate case_id={cid}")
        ids.add(cid)

        route = c.get("route", "")
        if route not in VALID_ROUTES:
            errors.append(f"retrieval_golden.jsonl: {cid} invalid route={route}")

        for ws in c.get("expected_workspace_ids", []):
            if ws not in VALID_WORKSPACES:
                errors.append(f"retrieval_golden.jsonl: {cid} unknown workspace={ws}")
        validate_chunk_uid_refs("retrieval_golden.jsonl", c, chunk_index)


def validate_qa_pairs(cases: list[dict], chunk_index: set[str] | None) -> None:
    route_counts: dict[str, int] = {}
    workspace_coverage: dict[str, int] = {}
    ids = set()

    for c in cases:
        cid = c.get("case_id", "")
        if not cid.startswith("qa_"):
            errors.append(f"qa_pairs.jsonl: case_id={cid} missing qa_ prefix")
        if cid in ids:
            errors.append(f"qa_pairs.jsonl: duplicate case_id={cid}")
        ids.add(cid)

        route = c.get("route", "")
        if route not in VALID_ROUTES:
            errors.append(f"qa_pairs.jsonl: {cid} invalid route={route}")
        route_counts[route] = route_counts.get(route, 0) + 1

        if "should_refuse" not in c:
            errors.append(f"qa_pairs.jsonl: {cid} missing should_refuse field")

        if c.get("should_refuse") and c.get("expected_tools"):
            errors.append(f"qa_pairs.jsonl: {cid} should_refuse=true but has expected_tools")

        ws = c.get("workspace_slug")
        if ws:
            workspace_coverage[ws] = workspace_coverage.get(ws, 0) + 1
        for ws_id in c.get("expected_workspace_ids", []):
            if ws_id not in VALID_WORKSPACES:
                errors.append(f"qa_pairs.jsonl: {cid} unknown workspace={ws_id}")
        validate_chunk_uid_refs("qa_pairs.jsonl", c, chunk_index)

    expected_counts = {
        "tech_general": 8,
        "project_specific": 8,
        "troubleshooting": 8,
        "out_of_scope": 4,
        "runbook_generation": 2,
    }
    for route, expected in expected_counts.items():
        actual = route_counts.get(route, 0)
        if actual < expected:
            errors.append(f"qa_pairs.jsonl: route={route} has {actual} cases, expected >={expected}")

    total = sum(route_counts.values())
    if total < 30:
        errors.append(f"qa_pairs.jsonl: only {total} cases, expected >=30")

    for ws in ["project_airflow", "project_backstage", "project_fastapi"]:
        if workspace_coverage.get(ws, 0) < 2:
            errors.append(f"qa_pairs.jsonl: workspace={ws} has <2 cases")


def main() -> int:
    print("Validating eval cases...")
    ret_cases = load_jsonl(EVAL_DIR / "retrieval_golden.jsonl")
    qa_cases = load_jsonl(EVAL_DIR / "qa_pairs.jsonl")
    chunk_index = load_chunk_index()

    all_ids = set()
    for c in ret_cases + qa_cases:
        cid = c.get("case_id", "")
        if cid in all_ids:
            errors.append(f"Cross-file duplicate case_id={cid}")
        all_ids.add(cid)

    validate_retrieval_golden(ret_cases, chunk_index)
    validate_qa_pairs(qa_cases, chunk_index)

    if errors:
        print(f"\nFAILED — {len(errors)} error(s):")
        for err in errors:
            print(f"  - {err}")
        return 1

    print(f"ALL CHECKS PASSED ({len(ret_cases)} retrieval + {len(qa_cases)} qa)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
