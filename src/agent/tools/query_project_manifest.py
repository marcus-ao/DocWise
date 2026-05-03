"""Read project/service metadata from data/mock/project_manifest.json."""
from __future__ import annotations

import json
from pathlib import Path

from src.agent.tools.schemas import ProjectManifestOutput
from src.common.exceptions import ToolExecutionError

_MANIFEST_PATH = Path("data/mock/project_manifest.json")


async def query_project_manifest(project_name: str | None = None, service_name: str | None = None) -> dict:
    try:
        data = _load_manifest()
        project_target = _normalize(project_name)
        service_target = _normalize(service_name)
        matched: list[dict] = []

        for project in data.get("projects", []):
            project_values = {
                _normalize(project.get("project_name")),
                _normalize(project.get("workspace_slug")),
                _normalize(project.get("display_name")),
            }
            project_matches = bool(project_target and project_target in project_values)
            for service in project.get("services", []):
                if project_matches or _matches_service(service, service_target):
                    matched.append(service)

        dependencies = sorted({item for svc in matched for item in svc.get("dependencies", [])})
        runbooks = sorted({item for svc in matched for item in svc.get("runbooks", [])})
        confidence = 1.0 if matched else 0.0
        return ProjectManifestOutput(
            matched_services=matched,
            dependencies=dependencies,
            runbooks=runbooks,
            confidence=confidence,
        ).model_dump()
    except Exception as exc:
        raise ToolExecutionError("query_project_manifest", str(exc)) from exc


def _load_manifest() -> dict:
    if not _MANIFEST_PATH.exists():
        return {"projects": []}
    return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))


def _normalize(value: str | None) -> str:
    return (value or "").strip().lower().replace("_", "-")


def _matches_service(service: dict, target: str) -> bool:
    if not target:
        return False
    values = [
        service.get("service_name"),
        service.get("display_name"),
        *(service.get("log_sources") or []),
        *(service.get("runbooks") or []),
    ]
    normalized = [_normalize(value) for value in values]
    if target == "airflow":
        return any(value.startswith("airflow-") or value == "airflow" for value in normalized)
    if target == "fastapi":
        return any("fastapi" in value or "api-gateway" in value for value in normalized)
    if target == "backstage":
        return any("backstage" in value for value in normalized)
    return any(target in value for value in normalized)

