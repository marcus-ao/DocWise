"""OpenAI-compatible chat client for DeepSeek/Qwen providers."""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, RateLimitError

from src.common.exceptions import NonRetryableError, RetryableError
from src.config.redactor import redact_secrets
from src.llm.model_router import get_model_name as _get_model_name
from src.llm.model_router import get_provider_config


def _client_for(model: str | None = None) -> tuple[AsyncOpenAI, str]:
    purpose = model if model in {None, "fast", "pro"} else None
    config = get_provider_config(purpose=purpose, model=None if model in {None, "fast", "pro"} else model)
    return AsyncOpenAI(base_url=config.base_url, api_key=config.api_key), config.model


def _fallback_candidates(model: str | None) -> list[str | None]:
    if model is None:
        return [None, "pro"]
    if model == "fast":
        return ["fast", "pro"]
    if model == "pro":
        return ["pro", "fast"]
    return [model]


def _map_openai_error(error: Exception) -> Exception:
    if isinstance(error, (RetryableError, NonRetryableError)):
        return error
    if isinstance(error, (APITimeoutError, APIConnectionError)):
        return RetryableError(redact_secrets(str(error)), backoff_seconds=2.0)
    if isinstance(error, RateLimitError):
        return RetryableError(redact_secrets(str(error)), backoff_seconds=5.0)
    if isinstance(error, APIStatusError):
        if error.status_code == 429:
            return RetryableError(redact_secrets(str(error)), backoff_seconds=5.0)
        return NonRetryableError(redact_secrets(str(error)))
    return NonRetryableError(redact_secrets(str(error)))


def _usage_to_dict(usage: Any) -> dict[str, int]:
    if usage is None:
        return {"prompt_tokens": 0, "completion_tokens": 0}
    return {
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
    }


async def chat_completion(
    messages: list[dict],
    model: str | None = None,
    temperature: float = 0,
    max_tokens: int | None = None,
    response_format: dict | None = None,
    stream: bool = False,
    timeout: float = 30.0,
    seed: int | None = None,
) -> dict:
    if stream:
        raise NonRetryableError("Use chat_completion_stream for stream=True")

    candidates = _fallback_candidates(model)
    for index, candidate in enumerate(candidates):
        client, model_name = _client_for(candidate)
        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "timeout": timeout,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if response_format is not None:
            kwargs["response_format"] = response_format
        if seed is not None:
            kwargs["seed"] = seed

        try:
            response = await client.chat.completions.create(**kwargs)
        except Exception as error:  # noqa: BLE001 - mapped into project contract exceptions.
            mapped_error = _map_openai_error(error)
            if index == len(candidates) - 1:
                raise mapped_error from error
            continue

        message = response.choices[0].message if response.choices else None
        return {
            "content": message.content if message and message.content else "",
            "usage": _usage_to_dict(response.usage),
        }

    raise NonRetryableError("LLM completion failed without response")


async def chat_completion_stream(
    messages: list[dict],
    model: str | None = None,
    temperature: float = 0,
    max_tokens: int | None = None,
    timeout: float = 60.0,
) -> AsyncIterator[str]:
    candidates = _fallback_candidates(model)
    for index, candidate in enumerate(candidates):
        client, model_name = _client_for(candidate)
        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
            "timeout": timeout,
            "stream": True,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        yielded = False
        try:
            stream = await client.chat.completions.create(**kwargs)
            async for chunk in stream:
                if not chunk.choices:
                    continue
                content = chunk.choices[0].delta.content
                if content:
                    yielded = True
                    yield content
            return
        except Exception as error:  # noqa: BLE001 - mapped into project contract exceptions.
            mapped_error = _map_openai_error(error)
            if yielded or index == len(candidates) - 1:
                raise mapped_error from error
            continue

    raise NonRetryableError("LLM stream failed without response")


def get_model_name(purpose: str) -> str:
    return _get_model_name(purpose)
