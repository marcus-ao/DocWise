import re

_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{10,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_.\-/+=]{10,}"),
    re.compile(r"token=[A-Za-z0-9_.\-/+=]{10,}"),
]

_ENV_KEYS = frozenset({
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "MINIO_SECRET_KEY",
    "POSTGRES_PASSWORD",
    "SECRET_KEY",
    "ADMIN_API_TOKEN",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_PUBLIC_KEY",
})


def redact_secrets(text: str) -> str:
    import os

    result = text
    for pattern in _PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    for key in _ENV_KEYS:
        value = os.environ.get(key)
        if value and len(value) > 4 and value in result:
            result = result.replace(value, "[REDACTED]")
    return result
