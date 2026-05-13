from __future__ import annotations

from uuid import uuid4

import pytest

from src.retrieval import keyword_search


class _UpdateResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _SelectResult:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def mappings(self) -> _SelectResult:
        return self

    def all(self) -> list[dict]:
        return list(self._rows)


class _FakeSession:
    def __init__(self, rows: list[dict], *, backfilled_rows: int = 0) -> None:
        self.rows = rows
        self.backfilled_rows = backfilled_rows
        self.executed: list[tuple[str, dict]] = []

    async def execute(self, stmt, params: dict):
        self.executed.append((str(stmt), dict(params)))
        if len(self.executed) == 1:
            return _UpdateResult(self.backfilled_rows)
        return _SelectResult(self.rows)


@pytest.mark.asyncio
async def test_keyword_search_uses_simple_config_for_chinese_queries_and_backfills_tsv() -> None:
    workspace_id = uuid4()
    session = _FakeSession(
        [
            {
                "chunk_id": uuid4(),
                "chunk_uid": "airflow:scheduler:abc123",
                "content": "scheduler heartbeat failure",
                "document_title": "Airflow Troubleshooting",
                "section_path": "scheduler > heartbeat",
                "workspace_id": str(workspace_id),
                "page_number": None,
                "doc_type": "tech_doc",
                "document_id": str(uuid4()),
                "keyword_score": 0.75,
            }
        ],
        backfilled_rows=2,
    )

    results = await keyword_search.search(session, "Airflow 调度失败", [workspace_id], top_k=5)

    assert len(session.executed) == 2
    assert "UPDATE document_chunks" in session.executed[0][0]
    assert "ELSE 'simple'" in session.executed[0][0]
    assert "plainto_tsquery('simple'" in session.executed[1][0]
    assert results[0]["chunk_uid"] == "airflow:scheduler:abc123"
    assert results[0]["keyword_score"] == 0.75
