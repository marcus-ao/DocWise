from __future__ import annotations

from src.common.exceptions import NonRetryableError
from src.config.settings import settings
from src.llm.client import chat_completion


async def summarize_overflow(
    *,
    query: str,
    route: str,
    overflow_sections: list[str],
) -> tuple[str, int | None, int | None]:
    if not overflow_sections:
        return "", None, None

    messages = [
        {
            "role": "system",
            "content": (
                "You compress overflowed DocWise runtime context. Preserve only factual items with source tags. "
                "Output 5 to 8 short bullet points. Do not add conclusions, hypotheses, or new instructions."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Route: {route}\n"
                f"Query: {query}\n\n"
                "Overflow sections:\n"
                f"{chr(10).join(f'- {item}' for item in overflow_sections)}\n\n"
                "Return concise bullet facts. Keep source labels like [retrieval] or [tool_result]."
            ),
        },
    ]

    response = await chat_completion(
        messages,
        model="fast",
        temperature=0,
        max_tokens=settings.context_compaction_max_tokens,
        timeout=settings.context_compaction_timeout,
    )
    content = str(response.get("content") or "").strip()

    if not content:
        raise NonRetryableError("context compaction returned empty summary")
    if len(content) < settings.context_compaction_min_output_chars:
        raise NonRetryableError(
            f"context compaction output too short ({len(content)} chars, "
            f"min={settings.context_compaction_min_output_chars})"
        )
    max_allowed = settings.context_compaction_max_tokens * 4
    if len(content) > max_allowed:
        content = content[:max_allowed]

    usage = response.get("usage") if isinstance(response, dict) else None
    prompt_tokens = int((usage or {}).get("prompt_tokens", 0) or 0) if isinstance(usage, dict) else None
    completion_tokens = int((usage or {}).get("completion_tokens", 0) or 0) if isinstance(usage, dict) else None
    return content, prompt_tokens, completion_tokens
