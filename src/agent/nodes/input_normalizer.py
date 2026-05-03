"""input_normalizer — strip, NFKC normalize, truncate."""
from __future__ import annotations

import time
import unicodedata

from langchain_core.runnables import RunnableConfig

from src.agent._tracer_stub import write_trace_event
from src.agent.state import AgentState

MAX_QUERY_LENGTH = 2000


async def input_normalizer(state: AgentState, config: RunnableConfig | None = None) -> AgentState:
    start = time.perf_counter()
    original = state["original_query"]

    cleaned = original.strip()
    cleaned = unicodedata.normalize("NFKC", cleaned)
    if len(cleaned) > MAX_QUERY_LENGTH:
        cleaned = cleaned[:MAX_QUERY_LENGTH]

    state["rewritten_query"] = cleaned

    elapsed = int((time.perf_counter() - start) * 1000)
    await write_trace_event(
        run_id=state["trace_id"],
        node_name="input_normalizer",
        sequence_no=1,
        status="success",
        input_summary={"original_length": len(original)},
        output_summary={"cleaned_length": len(cleaned)},
        latency_ms=elapsed,
    )
    return state
