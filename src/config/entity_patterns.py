"""Hard entity patterns preserved across query rewrite.

Each pattern carries its own case-sensitivity via an inline ``(?i)`` flag where
appropriate. The consuming compiler (``src.agent.rewriter.entities``) MUST NOT
apply a global ``re.IGNORECASE`` flag, otherwise the UPPERCASE-only matcher in
``error_code`` degrades into "any 3+ char ASCII word" and the critical-entity
guard starts rejecting almost every rewrite (e.g. EN→ZH paraphrases).
"""
from __future__ import annotations

ENTITY_PATTERNS: dict[str, str] = {
    # Error codes & strong acronyms: case-sensitive UPPERCASE identifiers (3+ chars)
    # OR a curated list of Pascal-cased runtime errors that must survive rewrite.
    "error_code": (
        r"\b(?:"
        r"[A-Z][A-Z0-9_]{2,}"
        r"|OOMKilled|CrashLoopBackOff"
        r"|SIGTERM|SIGKILL"
        r"|ECONNRESET|ETIMEDOUT|EPIPE|EAGAIN"
        r"|DB_TIMEOUT"
        r")\b"
    ),
    # HTTP status codes: concrete numeric 4xx/5xx or the literal 4xx/5xx pattern.
    "http_status": r"(?i)\b(?:[45]\d{2}|[45]xx)\b",
    # Version strings like 2.5.0, v2.5, V1.2.3.
    "version": r"(?i)\bv?\d+\.\d+(?:\.\d+)?\b",
    # File paths / config files — full absolute path OR a known config/code extension.
    "path": (
        r"(?i)(?:/[A-Za-z0-9_.\-/]+"
        r"|[A-Za-z0-9_.\-/]+\.(?:yaml|yml|toml|json|ini|cfg|conf|py|sh|md|txt|rst))"
    ),
    # Infra component / role names commonly used as precise anchors in tech queries.
    # Kept lowercase-friendly because users write "scheduler" / "Scheduler" / "SCHEDULER".
    "component": (
        r"(?i)\b(?:scheduler|executor|worker|broker|webserver|triggerer"
        r"|celery|kombu|redis|postgres|minio"
        r"|sidecar|operator|dagrun|taskinstance)\b"
    ),
}
