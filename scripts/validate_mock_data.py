"""Validate mock data files against tool_schemas.pyi Pydantic models."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import BaseModel, ValidationError

BASE_DIR = Path(__file__).resolve().parent.parent
MOCK_DIR = BASE_DIR / "data" / "mock"

SEED_PROJECT_NAMES = {
    "project_airflow": "data-platform",
    "project_backstage": "backstage-portal",
    "project_fastapi": "api-gateway",
}


# ============================================================
# Inline Pydantic models (mirror tool_schemas.pyi)
# ============================================================


class ServiceInfo(BaseModel):
    service_name: str
    display_name: str
    owner: str
    env: str
    tier: str
    sla: str
    dependencies: list[str]
    runbooks: list[str]
    dashboards: list[str]
    log_sources: list[str]


class MetricsInfo(BaseModel):
    cpu_percent: float
    memory_percent: float
    error_rate_5m: float
    p95_latency_ms: float


class AlertInfo(BaseModel):
    severity: str
    name: str
    started_at: str


class ServiceStatusEntry(BaseModel):
    service_name: str
    project_name: str
    status: str
    checked_at: str
    metrics: MetricsInfo
    active_alerts: list[AlertInfo]

class LogEntry(BaseModel):
    timestamp: str
    service_name: str
    component: str
    level: str
    message: str
    trace_id: str | None
    request_id: str | None
    error_code: str | None
    metadata: dict | None


class IncidentInfo(BaseModel):
    incident_id: str
    title: str
    service_name: str
    project_name: str
    severity: str
    status: str
    started_at: str
    resolved_at: str | None
    root_cause: str
    resolution: str
    affected_services: list[str]


# ============================================================
# Validators
# ============================================================

errors: list[str] = []


def known_service_names() -> set[str]:
    names: set[str] = set()
    manifest_path = MOCK_DIR / "project_manifest.json"
    if manifest_path.exists():
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        for project in data.get("projects", []):
            for service in project.get("services", []):
                if service.get("service_name"):
                    names.add(service["service_name"])
    return names


def validate_project_manifest() -> None:
    path = MOCK_DIR / "project_manifest.json"
    if not path.exists():
        errors.append(f"MISSING: {path}")
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    projects = data.get("projects", [])
    if not projects:
        errors.append("project_manifest.json: no projects found")
        return

    for proj in projects:
        pname = proj.get("project_name", "?")
        wslug = proj.get("workspace_slug", "?")
        expected_pname = SEED_PROJECT_NAMES.get(wslug)
        if expected_pname and pname != expected_pname:
            errors.append(
                f"project_manifest.json: workspace_slug={wslug} has project_name={pname}, "
                f"expected {expected_pname} (from seed_workspaces)"
            )
        for svc in proj.get("services", []):
            try:
                ServiceInfo(**svc)
            except ValidationError as exc:
                errors.append(f"project_manifest.json: service {svc.get('service_name','?')} invalid: {exc}")


def validate_service_status() -> None:
    path = MOCK_DIR / "service_status.json"
    if not path.exists():
        errors.append(f"MISSING: {path}")
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    valid_statuses = {"healthy", "degraded", "down", "unknown"}
    for svc in data.get("services", []):
        try:
            entry = ServiceStatusEntry(**svc)
            if entry.status not in valid_statuses:
                errors.append(
                    f"service_status.json: {entry.service_name} has invalid status={entry.status}"
                )
        except ValidationError as exc:
            errors.append(f"service_status.json: service {svc.get('service_name','?')} invalid: {exc}")


def validate_logs() -> None:
    logs_dir = MOCK_DIR / "logs"
    if not logs_dir.exists():
        errors.append(f"MISSING: {logs_dir}")
        return
    valid_levels = {"DEBUG", "INFO", "WARN", "ERROR"}
    for jsonl_file in sorted(logs_dir.glob("*.jsonl")):
        line_count = 0
        for i, line in enumerate(jsonl_file.read_text(encoding="utf-8").strip().splitlines(), 1):
            line_count += 1
            try:
                entry = LogEntry(**json.loads(line))
                if entry.level not in valid_levels:
                    errors.append(f"{jsonl_file.name}:{i}: invalid level={entry.level}")
            except (json.JSONDecodeError, ValidationError) as exc:
                errors.append(f"{jsonl_file.name}:{i}: {exc}")
        if line_count < 20:
            errors.append(f"{jsonl_file.name}: only {line_count} entries, expected >=20")


def validate_incidents() -> None:
    path = MOCK_DIR / "incidents.json"
    if not path.exists():
        errors.append(f"MISSING: {path}")
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    valid_severities = {"critical", "warning", "info"}
    valid_statuses = {"open", "investigating", "resolved"}
    services = known_service_names()
    seen_ids: set[str] = set()
    for item in data.get("incidents", []):
        try:
            incident = IncidentInfo(**item)
        except ValidationError as exc:
            errors.append(f"incidents.json: incident {item.get('incident_id','?')} invalid: {exc}")
            continue
        if incident.incident_id in seen_ids:
            errors.append(f"incidents.json: duplicate incident_id={incident.incident_id}")
        seen_ids.add(incident.incident_id)
        if incident.severity not in valid_severities:
            errors.append(f"incidents.json: {incident.incident_id} invalid severity={incident.severity}")
        if incident.status not in valid_statuses:
            errors.append(f"incidents.json: {incident.incident_id} invalid status={incident.status}")
        if services and incident.service_name not in services:
            errors.append(f"incidents.json: {incident.incident_id} unknown service={incident.service_name}")


def main() -> int:
    print("Validating mock data...")
    validate_project_manifest()
    validate_service_status()
    validate_logs()
    validate_incidents()

    if errors:
        print(f"\nFAILED — {len(errors)} error(s):")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
