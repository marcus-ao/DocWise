"""Import eval JSONL files into eval_cases."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from src.db.session import async_session_factory
from src.models.base import RouteType
from src.models.eval import EvalCase

EVAL_DIR = Path("data/eval")
FILES = ["retrieval_golden.jsonl", "qa_pairs.jsonl"]


def load_eval_cases(eval_dir: Path = EVAL_DIR) -> list[dict]:
    cases: list[dict] = []
    for file_name in FILES:
        path = eval_dir / file_name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                cases.append(json.loads(line))
    return cases


async def _upsert_eval_cases_with_session(session, cases: list[dict]) -> tuple[int, int]:
    inserted = 0
    updated = 0
    for item in cases:
        existing = await session.scalar(select(EvalCase).where(EvalCase.case_id == item["case_id"]))
        values = {
            "query": item["query"],
            "route": RouteType(item["route"]),
            "workspace_slug": item.get("workspace_slug"),
            "expected_workspace_ids": item.get("expected_workspace_ids"),
            "expected_answer_points": item.get("expected_answer_points"),
            "expected_chunk_uids": item.get("expected_chunk_uids"),
            "expected_tools": item.get("expected_tools"),
            "expected_citations": item.get("expected_citations"),
            "should_refuse": bool(item.get("should_refuse", False)),
            "tags": item.get("tags"),
        }
        if existing is None:
            session.add(EvalCase(case_id=item["case_id"], **values))
            inserted += 1
        else:
            for key, value in values.items():
                setattr(existing, key, value)
            updated += 1
    await session.commit()
    return inserted, updated


async def upsert_eval_cases(session_or_cases, cases: list[dict] | None = None) -> tuple[int, int]:
    if cases is not None:
        return await _upsert_eval_cases_with_session(session_or_cases, cases)
    async with async_session_factory() as session:
        return await _upsert_eval_cases_with_session(session, session_or_cases)


async def seed_eval_cases() -> tuple[int, int]:
    return await upsert_eval_cases(load_eval_cases())


async def main() -> None:
    inserted, updated = await seed_eval_cases()
    print(f"Seeded eval cases: inserted={inserted}, updated={updated}")


if __name__ == "__main__":
    asyncio.run(main())
