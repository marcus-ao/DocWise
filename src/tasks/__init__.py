__all__ = [
    "WorkerSettings",
    "process_eval_run",
    "process_ingest_document",
    "process_reindex",
]


def __getattr__(name: str):
    if name == "WorkerSettings":
        from src.tasks.worker import WorkerSettings

        return WorkerSettings
    if name in {"process_eval_run", "process_ingest_document", "process_reindex"}:
        from src.tasks import jobs

        return getattr(jobs, name)
    raise AttributeError(name)
