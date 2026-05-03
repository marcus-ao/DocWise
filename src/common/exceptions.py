"""Shared exception classes used across Agent, LLM, retrieval, and document modules."""

from __future__ import annotations


class RetryableError(Exception):
    """Retryable error with backoff hint."""

    def __init__(self, message: str, backoff_seconds: float = 1.0) -> None:
        super().__init__(message)
        self.backoff_seconds = backoff_seconds


class NonRetryableError(Exception):
    """Non-retryable error that should trigger degradation or fail fast."""


class ToolExecutionError(Exception):
    """Tool execution failure. Does not consume RetryBudget."""

    def __init__(self, tool_name: str, message: str) -> None:
        super().__init__(message)
        self.tool_name = tool_name
