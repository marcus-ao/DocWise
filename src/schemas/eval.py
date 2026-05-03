from uuid import UUID

from pydantic import BaseModel


class EvalRunRequest(BaseModel):
    case_filter: dict | None = None
    retry_failed: bool = False
    run_id: UUID | None = None


class EvalRunResponse(BaseModel):
    eval_run_id: UUID
    job_id: UUID
    status: str


class EvalSummary(BaseModel):
    run_id: UUID
    retrieval_hit_rate_at_5: float | None
    mrr_at_5: float | None
    workspace_accuracy: float | None
    citation_validity: float | None
    citation_coverage: float | None
    refusal_accuracy: float | None
    tool_call_accuracy: float | None
    answer_correctness_avg: float | None
    faithfulness_avg: float | None
    latency_p50_ms: int | None
    latency_p95_ms: int | None
    total_cases: int
    completed_cases: int
    failed_cases: int
    bad_case_count: int


class EvalResultDetail(BaseModel):
    case_id: str
    query: str
    route: str
    status: str
    agent_run_id: UUID | None
    retrieval_hit_rate: float | None
    mrr: float | None
    workspace_accuracy: bool | None
    citation_validity: float | None
    refusal_accuracy: bool | None
    tool_call_accuracy: float | None
    answer_correctness: float | None
    faithfulness: float | None
    latency_ms: int | None
    bad_case_types: list[str] | None
    error_message: str | None
