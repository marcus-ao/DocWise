"""Tracer stub — no-op fallback until Agent E lands src/observability/tracer.py."""
from __future__ import annotations

import uuid
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

try:
    import src.observability as _tracer
except ImportError:
    _tracer = None
    logger.warning("tracer_stub_active", msg="src.observability.tracer not available, using no-op stubs")


async def write_trace_event(*args: Any, **kwargs: Any) -> None:
    try:
        if _tracer is not None:
            await _tracer.write_trace_event(*args, **kwargs)
    except Exception as exc:
        logger.warning("trace_event_write_failed", error=str(exc))


async def write_retrieval_result(*args: Any, **kwargs: Any) -> None:
    try:
        if _tracer is not None:
            await _tracer.write_retrieval_result(*args, **kwargs)
    except Exception as exc:
        logger.warning("retrieval_result_write_failed", error=str(exc))


async def write_tool_call(*args: Any, **kwargs: Any) -> None:
    try:
        if _tracer is not None:
            await _tracer.write_tool_call(*args, **kwargs)
    except Exception as exc:
        logger.warning("tool_call_write_failed", error=str(exc))


async def create_agent_run(*args: Any, **kwargs: Any) -> str:
    try:
        if _tracer is not None:
            return await _tracer.create_agent_run(*args, **kwargs)
    except Exception as exc:
        logger.warning("agent_run_create_failed", error=str(exc))
    return str(uuid.uuid4())


async def complete_agent_run(*args: Any, **kwargs: Any) -> None:
    try:
        if _tracer is not None:
            await _tracer.complete_agent_run(*args, **kwargs)
    except Exception as exc:
        logger.warning("agent_run_complete_failed", error=str(exc))
