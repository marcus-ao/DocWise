"""runtime contract columns

Revision ID: 003
Revises: 002
Create Date: 2026-05-01
"""
from __future__ import annotations

from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_background_jobs_entity ON background_jobs (entity_type, entity_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tool_calls_run_id ON tool_calls (run_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_trace_events_run_id ON trace_events (run_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_trace_events_run_id")
    op.execute("DROP INDEX IF EXISTS ix_tool_calls_run_id")
    op.execute("DROP INDEX IF EXISTS ix_background_jobs_entity")

