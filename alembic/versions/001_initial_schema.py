"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-01
"""
from __future__ import annotations

import pgvector.sqlalchemy
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    workspace_type_values = ("public_tech", "project_pack", "mock_ops")
    doc_type_values = ("tech_doc", "sop", "runbook", "api_doc", "log_doc")
    document_status_values = ("pending", "processing", "ready", "error")
    chunk_language_values = ("en", "zh", "mixed")
    route_type_values = ("tech_general", "project_specific", "troubleshooting", "runbook_generation", "out_of_scope")
    agent_run_status_values = ("running", "succeeded", "failed", "refused")
    retrieval_stage_values = ("vector", "keyword", "rrf", "rerank")
    trace_event_status_values = ("success", "error", "skipped")
    tool_call_status_values = ("success", "error")
    job_type_values = ("ingest_document", "reindex_document", "batch_ingest", "eval_run")
    job_status_values = ("queued", "running", "succeeded", "failed", "cancelled", "retrying")
    entity_type_values = ("document", "workspace", "eval")

    for enum_name, enum_values in [
        ("workspace_type", workspace_type_values),
        ("doc_type", doc_type_values),
        ("document_status", document_status_values),
        ("chunk_language", chunk_language_values),
        ("route_type", route_type_values),
        ("agent_run_status", agent_run_status_values),
        ("retrieval_stage", retrieval_stage_values),
        ("trace_event_status", trace_event_status_values),
        ("tool_call_status", tool_call_status_values),
        ("job_type", job_type_values),
        ("job_status", job_status_values),
        ("entity_type", entity_type_values),
    ]:
        postgresql.ENUM(*enum_values, name=enum_name).create(op.get_bind(), checkfirst=True)

    workspace_type = postgresql.ENUM(*workspace_type_values, name="workspace_type", create_type=False)
    doc_type = postgresql.ENUM(*doc_type_values, name="doc_type", create_type=False)
    document_status = postgresql.ENUM(*document_status_values, name="document_status", create_type=False)
    chunk_language = postgresql.ENUM(*chunk_language_values, name="chunk_language", create_type=False)
    route_type = postgresql.ENUM(*route_type_values, name="route_type", create_type=False)
    agent_run_status = postgresql.ENUM(*agent_run_status_values, name="agent_run_status", create_type=False)
    retrieval_stage = postgresql.ENUM(*retrieval_stage_values, name="retrieval_stage", create_type=False)
    trace_event_status = postgresql.ENUM(*trace_event_status_values, name="trace_event_status", create_type=False)
    tool_call_status = postgresql.ENUM(*tool_call_status_values, name="tool_call_status", create_type=False)
    job_type = postgresql.ENUM(*job_type_values, name="job_type", create_type=False)
    job_status = postgresql.ENUM(*job_status_values, name="job_status", create_type=False)
    entity_type = postgresql.ENUM(*entity_type_values, name="entity_type", create_type=False)

    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(128), nullable=False, unique=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("workspace_type", workspace_type, nullable=False),
        sa.Column("project_name", sa.String(256), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_workspaces_slug", "workspaces", ["slug"])

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column("storage_bucket", sa.String(128), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("doc_type", doc_type, nullable=False),
        sa.Column("status", document_status, nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("parser_name", sa.String(128), nullable=True),
        sa.Column("parser_version", sa.String(64), nullable=True),
        sa.Column("chunk_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("embedding_model", sa.String(128), nullable=True),
        sa.Column("embedding_dim", sa.Integer(), nullable=True),
        sa.Column("index_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_documents_content_hash", "documents", ["content_hash"])

    op.create_table(
        "document_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("chunk_uid", sa.String(256), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("section_title", sa.String(256), nullable=True),
        sa.Column("section_path", sa.Text(), nullable=True),
        sa.Column("heading_level", sa.Integer(), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("start_char", sa.Integer(), nullable=True),
        sa.Column("end_char", sa.Integer(), nullable=True),
        sa.Column("source_anchor", sa.String(256), nullable=True),
        sa.Column("doc_type", doc_type, nullable=False),
        sa.Column("language", chunk_language, nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(2048), nullable=True),
        sa.Column("content_tsv", postgresql.TSVECTOR(), nullable=True),
        sa.Column("embedding_model", sa.String(128), nullable=True),
        sa.Column("embedding_dim", sa.Integer(), nullable=True),
        sa.Column("index_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_document_chunks_chunk_uid", "document_chunks", ["chunk_uid"])

    op.create_table(
        "queries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("original_query", sa.Text(), nullable=False),
        sa.Column("rewritten_query", sa.Text(), nullable=True),
        sa.Column("workspace_slug", sa.String(128), nullable=True),
        sa.Column("route", route_type, nullable=True),
        sa.Column("route_confidence", sa.Float(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("refused", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("refusal_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("query_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("queries.id"), nullable=False),
        sa.Column("original_query", sa.Text(), nullable=False),
        sa.Column("route", route_type, nullable=True),
        sa.Column("route_confidence", sa.Float(), nullable=True),
        sa.Column("workspace_policy", sa.String(64), nullable=True),
        sa.Column("workspace_ids", postgresql.JSONB(), nullable=True),
        sa.Column("status", agent_run_status, nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("final_citations", postgresql.JSONB(), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("refused", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("refusal_reason", sa.Text(), nullable=True),
        sa.Column("langfuse_trace_id", sa.String(128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("model_summary", postgresql.JSONB(), nullable=True),
        sa.Column("token_usage", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_agent_runs_query_id", "agent_runs", ["query_id"])

    op.create_table(
        "retrieval_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("query_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("queries.id"), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("document_chunks.id"), nullable=False),
        sa.Column("chunk_uid", sa.String(256), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vector_score", sa.Float(), nullable=True),
        sa.Column("keyword_score", sa.Float(), nullable=True),
        sa.Column("rrf_score", sa.Float(), nullable=True),
        sa.Column("rerank_score", sa.Float(), nullable=True),
        sa.Column("final_rank", sa.Integer(), nullable=True),
        sa.Column("retrieval_stage", retrieval_stage, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "tool_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("tool_name", sa.String(64), nullable=False),
        sa.Column("call_index", sa.Integer(), nullable=False),
        sa.Column("input_json", postgresql.JSONB(), nullable=False),
        sa.Column("output_json", postgresql.JSONB(), nullable=True),
        sa.Column("status", tool_call_status, nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "trace_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("node_name", sa.String(64), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("status", trace_event_status, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("input_summary", postgresql.JSONB(), nullable=True),
        sa.Column("output_summary", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "background_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("arq_job_id", sa.String(128), nullable=True),
        sa.Column("job_type", job_type, nullable=False),
        sa.Column("status", job_status, nullable=False),
        sa.Column("entity_type", entity_type, nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dedupe_key", sa.String(256), nullable=True, unique=True),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("progress", postgresql.JSONB(), nullable=True),
        sa.Column("input_json", postgresql.JSONB(), nullable=True),
        sa.Column("result_json", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_retries", sa.Integer(), server_default="3", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("query_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("queries.id"), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("thumbs", sa.String(8), nullable=True),
        sa.Column("correction", sa.Text(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "eval_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("case_id", sa.String(128), unique=True, nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("route", route_type, nullable=False),
        sa.Column("workspace_slug", sa.String(128), nullable=True),
        sa.Column("expected_workspace_ids", postgresql.JSONB(), nullable=True),
        sa.Column("expected_answer_points", postgresql.JSONB(), nullable=True),
        sa.Column("expected_chunk_uids", postgresql.JSONB(), nullable=True),
        sa.Column("expected_tools", postgresql.JSONB(), nullable=True),
        sa.Column("expected_citations", postgresql.JSONB(), nullable=True),
        sa.Column("should_refuse", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("tags", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_eval_cases_case_id", "eval_cases", ["case_id"])

    op.create_table(
        "eval_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("eval_cases.id"), nullable=False),
        sa.Column("agent_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_runs.id"), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("retrieval_hit_rate", sa.Float(), nullable=True),
        sa.Column("mrr", sa.Float(), nullable=True),
        sa.Column("workspace_accuracy", sa.Boolean(), nullable=True),
        sa.Column("citation_validity", sa.Float(), nullable=True),
        sa.Column("citation_coverage", sa.Float(), nullable=True),
        sa.Column("refusal_accuracy", sa.Boolean(), nullable=True),
        sa.Column("tool_call_accuracy", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("answer_correctness", sa.Float(), nullable=True),
        sa.Column("faithfulness", sa.Float(), nullable=True),
        sa.Column("bad_case_types", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    for table in [
        "eval_results",
        "eval_cases",
        "feedback",
        "background_jobs",
        "trace_events",
        "tool_calls",
        "retrieval_results",
        "agent_runs",
        "queries",
        "document_chunks",
        "documents",
        "workspaces",
    ]:
        op.drop_table(table)

    for name in [
        "entity_type",
        "job_status",
        "job_type",
        "tool_call_status",
        "trace_event_status",
        "retrieval_stage",
        "agent_run_status",
        "route_type",
        "chunk_language",
        "document_status",
        "doc_type",
        "workspace_type",
    ]:
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)
