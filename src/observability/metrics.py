"""P0 deterministic evaluation metrics."""
from __future__ import annotations

import math


def uid_matches(expected_uid: str, actual_uid: str) -> bool:
    """Fuzzy prefix match: 'airflow-runbook:task-failure:*' matches any uid with that prefix."""
    if expected_uid.endswith("*"):
        return actual_uid.startswith(expected_uid[:-1])
    return actual_uid == expected_uid


def hit_rate_at_k(expected_uids: list[str], actual_uids: list[str], k: int = 5) -> float:
    """Fraction of expected UIDs that appear in actual top-k (with fuzzy matching)."""
    if not expected_uids:
        return 0.0
    actual_top_k = actual_uids[:k]
    hits = 0
    for expected in expected_uids:
        if any(uid_matches(expected, actual) for actual in actual_top_k):
            hits += 1
    return hits / len(expected_uids)


def mrr_at_k(expected_uids: list[str], actual_uids: list[str], k: int = 5) -> float:
    """Reciprocal rank of first expected UID hit in actual top-k."""
    actual_top_k = actual_uids[:k]
    for rank, actual in enumerate(actual_top_k, start=1):
        if any(uid_matches(expected, actual) for expected in expected_uids):
            return 1.0 / rank
    return 0.0


def workspace_accuracy(expected_ids: list[str], actual_ids: list[str]) -> bool:
    """True if expected workspace set is a subset of actual workspace set."""
    return set(expected_ids) <= set(actual_ids)


def citation_validity(actual_citations: list[str], reranked_chunk_uids: list[str]) -> float:
    """Fraction of actual citations that come from reranked chunks."""
    if not actual_citations:
        return 1.0
    valid = sum(1 for c in actual_citations if c in reranked_chunk_uids)
    return valid / len(actual_citations)


def citation_coverage(expected_citations: list[str], actual_citations: list[str]) -> float:
    """Fraction of expected citations covered by actual citations (with fuzzy matching)."""
    if not expected_citations:
        return 1.0
    covered = 0
    for expected in expected_citations:
        if any(uid_matches(expected, actual) for actual in actual_citations):
            covered += 1
    return covered / len(expected_citations)


def refusal_accuracy(should_refuse: bool, actually_refused: bool) -> bool:
    """True if refusal decision matches expectation."""
    return should_refuse == actually_refused


def tool_call_accuracy(expected_tools: list[str], actual_tools: list[str]) -> float:
    """Jaccard similarity between expected and actual tool sets."""
    expected_set = set(expected_tools)
    actual_set = set(actual_tools)
    union = expected_set | actual_set
    if not union:
        return 1.0
    return len(expected_set & actual_set) / len(union)


def latency_percentile(latencies: list[int], percentile: float = 95.0) -> int | None:
    """Compute the given percentile from a list of latency values in ms."""
    if not latencies:
        return None
    sorted_vals = sorted(latencies)
    idx = (percentile / 100.0) * (len(sorted_vals) - 1)
    lower = int(math.floor(idx))
    upper = int(math.ceil(idx))
    if lower == upper:
        return sorted_vals[lower]
    frac = idx - lower
    return int(sorted_vals[lower] + frac * (sorted_vals[upper] - sorted_vals[lower]))
