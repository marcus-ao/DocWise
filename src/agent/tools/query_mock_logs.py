"""Read deterministic mock logs from data/mock/logs."""
from __future__ import annotations

import json
from pathlib import Path

from src.agent.tools.schemas import QueryLogsOutput
from src.common.exceptions import ToolExecutionError

_LOG_DIR = Path("data/mock/logs")


async def query_mock_logs(
    service_name: str,
    time_range: str = "last_30m",
    level: str | None = None,
    keywords: list[str] | None = None,
) -> dict:
    try:
        entries: list[dict] = []
        paths = _candidate_paths(service_name)
        for path in paths:
            entries.extend(_load_jsonl(path))

        target_level = (level or "").upper()
        if target_level:
            entries = [entry for entry in entries if str(entry.get("level", "")).upper() == target_level]

        terms = _keyword_terms(keywords or [])
        if terms:
            entries = [entry for entry in entries if _matches_keywords(str(entry.get("message", "")), terms)]

        entries = sorted(entries, key=lambda item: item.get("timestamp", ""), reverse=True)
        summary = _summary(service_name, entries, target_level, time_range, paths)
        return QueryLogsOutput(
            service_name=service_name,
            time_range=time_range,
            matched_count=len(entries),
            entries=entries[:20],
            summary=summary,
        ).model_dump()
    except Exception as exc:
        raise ToolExecutionError("query_mock_logs", str(exc)) from exc


def _normalize(value: str | None) -> str:
    return (value or "").strip().lower().replace("_", "-")


def _candidate_paths(service_name: str) -> list[Path]:
    target = _normalize(service_name)
    if not _LOG_DIR.exists():
        return []
    all_paths = sorted(_LOG_DIR.glob("*.jsonl"))
    if target == "airflow":
        return [path for path in all_paths if path.stem.startswith("airflow-")]
    if target == "fastapi":
        return [path for path in all_paths if "fastapi" in path.stem or "api-gateway" in path.stem]
    if target == "backstage":
        return [path for path in all_paths if "backstage" in path.stem]
    exact = _LOG_DIR / f"{target}.jsonl"
    if exact.exists():
        return [exact]
    return [path for path in all_paths if target and target in path.stem]


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _keyword_terms(keywords: list[str]) -> list[list[str]]:
    terms: list[list[str]] = []
    for keyword in keywords:
        tokens = [token for token in _normalize(keyword).split() if token]
        if tokens:
            terms.append(tokens)
    return terms


def _matches_keywords(message: str, terms: list[list[str]]) -> bool:
    normalized = _normalize(message)
    return any(all(token in normalized for token in group) for group in terms)


def _summary(service_name: str, entries: list[dict], level: str, time_range: str, paths: list[Path]) -> str:
    if not paths:
        return f"No log file found for service '{service_name}'."
    if not entries:
        return f"No {level or 'matching'} logs found for {service_name} in {time_range}."
    services = sorted({str(entry.get("service_name")) for entry in entries})
    codes = sorted({str(entry.get("error_code")) for entry in entries if entry.get("error_code")})
    code_text = ", ".join(codes[:8])
    if len(codes) > 8:
        code_text += ", ..."
    return f"Found {len(entries)} {level or ''} log entries for {', '.join(services)}. Error codes: {code_text}".strip()

