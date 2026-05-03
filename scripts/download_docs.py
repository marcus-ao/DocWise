"""Generate deterministic local sample documents for DocWise demos."""
from __future__ import annotations

from pathlib import Path

SAMPLES = {
    "data/raw/airflow/airflow-task-failure.md": """# Airflow Task Failure

## Scheduler Heartbeat
When tasks remain queued, inspect the scheduler heartbeat and DagFileProcessor logs.

## Worker Logs
Check worker logs for database timeout, OOM, and retry exhaustion signals.
""",
    "data/raw/airflow/airflow-runbook.md": """# Airflow Runbook

## Task Failure
1. Confirm scheduler health.
2. Review worker logs for DB_TIMEOUT or OOM.
3. Check retry configuration and upstream dependencies.
""",
    "data/raw/backstage/backstage-catalog.md": """# Backstage Catalog

## Sync Failure
Catalog sync depends on GitHub API reachability and database migrations.

## Plugin Errors
Plugin startup failures should be checked in backstage-backend logs.
""",
    "data/raw/backstage/backstage-techdocs.md": """# Backstage TechDocs

## Publishing
TechDocs publishing requires a configured builder and object storage target.
""",
    "data/raw/fastapi-docs/fastapi-latency.md": """# FastAPI Latency

## Connection Pool
High p95 latency can be caused by database connection pool exhaustion.

## Mitigation
Tune pool size, inspect slow queries, and verify downstream service latency.
""",
    "data/raw/fastapi-docs/fastapi-deployment.md": """# FastAPI Deployment

## Health Checks
Expose readiness checks for database and Redis dependencies.
""",
    "data/raw/enterprise-sops/db-change.md": """# Database Change SOP

## Rollback
Every schema change requires a rollback plan and validation query.
""",
}


def main() -> None:
    for path, content in SAMPLES.items():
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        print(f"Wrote {target}")


if __name__ == "__main__":
    main()
