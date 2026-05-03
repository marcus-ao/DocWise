"""Generate deterministic mock operations data and retrieval eval fixtures."""
from __future__ import annotations

import json
from pathlib import Path

MOCK_DIR = Path("data/mock")
LOG_DIR = MOCK_DIR / "logs"
EVAL_DIR = Path("data/eval")


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def project_manifest() -> dict:
    return {
        "projects": [
            {
                "workspace_slug": "project_airflow",
                "project_name": "data-platform",
                "display_name": "Airflow Data Platform",
                "services": [
                    {
                        "service_name": "airflow-scheduler",
                        "display_name": "Airflow Scheduler",
                        "owner": "data-infra",
                        "env": "prod",
                        "tier": "critical",
                        "sla": "99.9%",
                        "dependencies": ["postgres-airflow", "redis-broker"],
                        "runbooks": ["airflow-task-failure", "airflow-scheduler-restart"],
                        "dashboards": ["airflow-prod-overview", "airflow-dag-metrics"],
                        "log_sources": ["airflow-scheduler", "airflow-worker"],
                    },
                    {
                        "service_name": "airflow-worker",
                        "display_name": "Airflow Worker",
                        "owner": "data-infra",
                        "env": "prod",
                        "tier": "critical",
                        "sla": "99.9%",
                        "dependencies": ["airflow-scheduler", "postgres-airflow", "redis-broker"],
                        "runbooks": ["airflow-worker-oom-runbook", "airflow-task-failure"],
                        "dashboards": ["airflow-prod-overview", "airflow-worker-resources"],
                        "log_sources": ["airflow-worker"],
                    },
                ],
            },
            {
                "workspace_slug": "project_backstage",
                "project_name": "backstage-portal",
                "display_name": "Backstage Developer Portal",
                "services": [
                    {
                        "service_name": "backstage-backend",
                        "display_name": "Backstage Backend",
                        "owner": "platform-eng",
                        "env": "prod",
                        "tier": "standard",
                        "sla": "99.5%",
                        "dependencies": ["postgres-backstage", "catalog-provider"],
                        "runbooks": ["backstage-catalog-sync"],
                        "dashboards": ["backstage-overview"],
                        "log_sources": ["backstage-backend"],
                    }
                ],
            },
            {
                "workspace_slug": "project_fastapi",
                "project_name": "api-gateway",
                "display_name": "FastAPI Gateway",
                "services": [
                    {
                        "service_name": "fastapi-app",
                        "display_name": "FastAPI App",
                        "owner": "gateway-team",
                        "env": "prod",
                        "tier": "critical",
                        "sla": "99.9%",
                        "dependencies": ["redis-cache", "auth-service"],
                        "runbooks": ["fastapi-latency-runbook"],
                        "dashboards": ["fastapi-gateway-overview"],
                        "log_sources": ["fastapi-app"],
                    }
                ],
            },
        ]
    }


def service_status() -> dict:
    return {
        "services": [
            {
                "service_name": "airflow-scheduler",
                "project_name": "data-platform",
                "status": "degraded",
                "checked_at": "2026-04-29T10:30:00Z",
                "metrics": {
                    "cpu_percent": 78.3,
                    "memory_percent": 84.1,
                    "error_rate_5m": 0.12,
                    "p95_latency_ms": 1200.0,
                },
                "active_alerts": [
                    {"severity": "critical", "name": "SchedulerHeartbeatMissing", "started_at": "2026-04-29T10:14:00Z"},
                    {"severity": "warning", "name": "HighMemoryUsage", "started_at": "2026-04-29T10:18:00Z"},
                ],
            },
            {
                "service_name": "airflow-worker",
                "project_name": "data-platform",
                "status": "down",
                "checked_at": "2026-04-29T10:30:00Z",
                "metrics": {
                    "cpu_percent": 95.2,
                    "memory_percent": 97.8,
                    "error_rate_5m": 0.45,
                    "p95_latency_ms": 2100.0,
                },
                "active_alerts": [
                    {"severity": "critical", "name": "WorkerOOM", "started_at": "2026-04-29T10:20:00Z"},
                    {"severity": "critical", "name": "TaskFailureRateHigh", "started_at": "2026-04-29T10:15:00Z"},
                ],
            },
            {
                "service_name": "backstage-backend",
                "project_name": "backstage-portal",
                "status": "degraded",
                "checked_at": "2026-04-29T10:30:00Z",
                "metrics": {"cpu_percent": 62.4, "memory_percent": 71.5, "error_rate_5m": 0.08, "p95_latency_ms": 980.0},
                "active_alerts": [
                    {"severity": "warning", "name": "CatalogProviderLag", "started_at": "2026-04-29T10:05:00Z"}
                ],
            },
            {
                "service_name": "fastapi-app",
                "project_name": "api-gateway",
                "status": "healthy",
                "checked_at": "2026-04-29T10:30:00Z",
                "metrics": {"cpu_percent": 41.2, "memory_percent": 55.3, "error_rate_5m": 0.01, "p95_latency_ms": 120.0},
                "active_alerts": [],
            },
        ]
    }


def incidents() -> dict:
    return {
        "incidents": [
            {
                "incident_id": "inc_airflow_001",
                "title": "Airflow worker OOM caused task failures",
                "service_name": "airflow-worker",
                "project_name": "data-platform",
                "severity": "critical",
                "status": "investigating",
                "started_at": "2026-04-29T10:15:00Z",
                "resolved_at": None,
                "root_cause": "Worker memory saturation and retry exhaustion.",
                "resolution": "Scale worker memory and reduce parallelism until stable.",
                "affected_services": ["airflow-worker", "airflow-scheduler"],
            },
            {
                "incident_id": "inc_backstage_001",
                "title": "Backstage catalog sync lag",
                "service_name": "backstage-backend",
                "project_name": "backstage-portal",
                "severity": "warning",
                "status": "resolved",
                "started_at": "2026-04-29T09:40:00Z",
                "resolved_at": "2026-04-29T10:05:00Z",
                "root_cause": "Catalog provider timeout.",
                "resolution": "Increased provider timeout and retried sync.",
                "affected_services": ["backstage-backend"],
            },
        ]
    }


def airflow_scheduler_logs() -> list[dict]:
    rows = []
    messages = [
        ("ERROR", "TASK_QUEUE_FAIL", "Failed to queue task daily_sales_etl.extract_orders: database connection refused"),
        ("WARN", "SCHEDULER_HEARTBEAT_LAG", "Scheduler heartbeat delayed by 45 seconds"),
        ("INFO", None, "DagFileProcessor completed parsing daily_sales_etl.py"),
    ]
    for i in range(24):
        level, code, message = messages[i % len(messages)]
        rows.append(_log("airflow-scheduler", "scheduler", level, message, code, i))
    return rows


def airflow_worker_logs() -> list[dict]:
    important = [
        ("ERROR", "OOM", "Task daily_sales_etl.extract_orders failed: MemoryError unable to allocate 2.1 GiB"),
        ("ERROR", "RETRY_EXHAUSTED", "Task daily_sales_etl.extract_orders max retries exhausted, marking as FAILED"),
        ("ERROR", "DB_CONN_REFUSED", "Task hourly_metrics_agg.publish failed: ConnectionRefusedError to postgres-airflow:5432"),
        ("ERROR", "TASK_TIMEOUT", "Task data_quality_check.run_checks failed: TimeoutError after 60s"),
        ("ERROR", "WORKER_RESTART", "Worker restarting after OOM kill, 3 tasks lost"),
        ("ERROR", "POOL_EXHAUSTED", "Task weekly_report_gen.collect_data failed: database connection pool exhausted"),
        ("ERROR", "DEGRADED_MODE", "Multiple task failures detected, worker entering degraded mode"),
        ("ERROR", "HEALTH_CHECK_FAIL", "Worker health check failed: 0 of 16 slots available, all tasks stalled"),
    ]
    rows = [_log("airflow-worker", "task_runner", level, message, code, i) for i, (level, code, message) in enumerate(important)]
    for i in range(16):
        rows.append(_log("airflow-worker", "worker", "INFO", f"Heartbeat ok with active_slots={i % 5}", None, i + 8))
    return rows


def generic_logs(service_name: str) -> list[dict]:
    rows = []
    for i in range(20):
        level = "ERROR" if i in {3, 11} else "INFO"
        code = "REQUEST_ERROR" if level == "ERROR" else None
        message = f"{service_name} request {'failed' if level == 'ERROR' else 'completed'} for operation {i}"
        rows.append(_log(service_name, "app", level, message, code, i))
    return rows


def _log(service_name: str, component: str, level: str, message: str, error_code: str | None, index: int) -> dict:
    return {
        "timestamp": f"2026-04-29T10:{index % 30:02d}:00Z",
        "service_name": service_name,
        "component": component,
        "level": level,
        "message": message,
        "trace_id": f"trc_{service_name.replace('-', '_')}_{index:03d}",
        "request_id": f"req_{index:03d}",
        "error_code": error_code,
        "metadata": {"sequence": index},
    }


def retrieval_cases() -> list[dict]:
    cases = []
    templates = [
        ("Airflow task failure troubleshooting", "troubleshooting", "project_airflow", ["project_airflow", "public_tech"], ["airflow-runbook:*", "airflow-task-failure:*"]),
        ("Airflow scheduler heartbeat missing", "troubleshooting", "project_airflow", ["project_airflow", "public_tech"], ["airflow-task-failure:*"]),
        ("FastAPI latency troubleshooting", "project_specific", "project_fastapi", ["project_fastapi"], ["fastapi-latency:*"]),
        ("Backstage catalog-info.yaml example", "project_specific", "project_backstage", ["project_backstage"], ["backstage-catalog:*"]),
        ("General database change SOP", "tech_general", None, ["public_tech"], ["db-change:*"]),
    ]
    for i in range(20):
        query, route, workspace_slug, workspaces, chunks = templates[i % len(templates)]
        cases.append(
            {
                "case_id": f"ret_{i + 1:03d}",
                "query": f"{query} case {i + 1}",
                "route": route,
                "workspace_slug": workspace_slug,
                "expected_workspace_ids": workspaces,
                "expected_chunk_uids": chunks,
                "expected_citations": chunks[:1],
                "tags": ["retrieval", route],
            }
        )
    return cases


def main() -> None:
    _write_json(MOCK_DIR / "project_manifest.json", project_manifest())
    _write_json(MOCK_DIR / "service_status.json", service_status())
    _write_json(MOCK_DIR / "incidents.json", incidents())
    _write_jsonl(LOG_DIR / "airflow-scheduler.jsonl", airflow_scheduler_logs())
    _write_jsonl(LOG_DIR / "airflow-worker.jsonl", airflow_worker_logs())
    _write_jsonl(LOG_DIR / "backstage-backend.jsonl", generic_logs("backstage-backend"))
    _write_jsonl(LOG_DIR / "fastapi-app.jsonl", generic_logs("fastapi-app"))
    _write_jsonl(EVAL_DIR / "retrieval_golden.jsonl", retrieval_cases())
    print("Generated mock operations data and retrieval eval cases.")


if __name__ == "__main__":
    main()

