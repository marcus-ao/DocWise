"""query_service_status tool — read data/mock/service_status.json."""
from __future__ import annotations

import json
from pathlib import Path

import structlog

from src.agent.tools.schemas import ServiceStatusOutput
from src.common.exceptions import ToolExecutionError

logger = structlog.get_logger(__name__)

_STATUS_PATH = Path("data/mock/service_status.json")
_DEFAULT_METRICS = {
    "cpu_percent": 0.0,
    "memory_percent": 0.0,
    "error_rate_5m": 0.0,
    "p95_latency_ms": 0.0,
}


async def query_service_status(service_name: str) -> dict:
    try:
        data = _load_status()
        services = data.get("services", [])

        for svc in services:
            if _normalize(svc["service_name"]) == _normalize(service_name):
                return _status_output(svc)

        candidates = [svc for svc in services if _matches_service(svc, service_name)]
        if candidates:
            return _status_output(max(candidates, key=_status_priority))

        return ServiceStatusOutput(
            service_name=service_name,
            status="unknown",
            metrics=_DEFAULT_METRICS.copy(),
            active_alerts=[],
            checked_at="",
        ).model_dump()
    except Exception as exc:
        raise ToolExecutionError("query_service_status", str(exc)) from exc


def _load_status() -> dict:
    if not _STATUS_PATH.exists():
        return {"services": []}
    return json.loads(_STATUS_PATH.read_text(encoding="utf-8"))


def _normalize(value: str | None) -> str:
    return (value or "").strip().lower().replace("_", "-")


def _matches_service(service: dict, service_name: str) -> bool:
    target = _normalize(service_name)
    if not target:
        return False
    values = [service.get("service_name"), service.get("project_name")]
    return any(target in _normalize(value) for value in values)


def _status_priority(service: dict) -> tuple[int, float, float]:
    status_rank = {"unknown": 0, "healthy": 1, "degraded": 2, "down": 3}
    metrics = service.get("metrics", {})
    return (
        status_rank.get(str(service.get("status", "unknown")), 0),
        float(metrics.get("error_rate_5m") or 0.0),
        float(metrics.get("memory_percent") or 0.0),
    )


def _status_output(service: dict) -> dict:
    return ServiceStatusOutput(
        service_name=service["service_name"],
        status=service.get("status", "unknown"),
        metrics={**_DEFAULT_METRICS, **service.get("metrics", {})},
        active_alerts=service.get("active_alerts", []),
        checked_at=service.get("checked_at", ""),
    ).model_dump()
