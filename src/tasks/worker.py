"""arq worker settings for DocWise background jobs."""
from __future__ import annotations

from urllib.parse import urlparse

from arq.connections import RedisSettings

from src.config.settings import settings
from src.tasks.jobs import process_eval_run, process_ingest_document, process_reindex


def _redis_settings_from_url(redis_url: str) -> RedisSettings:
    parsed = urlparse(redis_url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int(parsed.path.strip("/") or "0"),
        password=parsed.password,
    )


class WorkerSettings:
    functions = [process_ingest_document, process_reindex, process_eval_run]
    redis_settings = _redis_settings_from_url(settings.redis_url)
    max_jobs = 5
    job_timeout = settings.arq_default_timeout
    keep_result = settings.arq_result_ttl
    health_check_interval = 30
