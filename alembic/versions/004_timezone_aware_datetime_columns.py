"""ensure runtime datetime columns are timezone aware

Revision ID: 004
Revises: 003
Create Date: 2026-05-02
"""

from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


TIMEZONE_COLUMNS = [
    ("workspaces", "created_at"),
    ("workspaces", "updated_at"),
    ("documents", "indexed_at"),
    ("documents", "created_at"),
    ("documents", "updated_at"),
    ("document_chunks", "created_at"),
    ("document_chunks", "updated_at"),
    ("queries", "created_at"),
    ("agent_runs", "started_at"),
    ("agent_runs", "ended_at"),
    ("agent_runs", "created_at"),
    ("retrieval_results", "created_at"),
    ("tool_calls", "started_at"),
    ("tool_calls", "ended_at"),
    ("trace_events", "started_at"),
    ("trace_events", "ended_at"),
    ("trace_events", "created_at"),
    ("background_jobs", "started_at"),
    ("background_jobs", "finished_at"),
    ("background_jobs", "created_at"),
    ("background_jobs", "updated_at"),
    ("feedback", "created_at"),
    ("eval_cases", "created_at"),
    ("eval_results", "created_at"),
]


def _alter_column_type(table_name: str, column_name: str, from_type: str, to_type_sql: str, using_sql: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = '{table_name}'
                  AND column_name = '{column_name}'
                  AND data_type = '{from_type}'
            ) THEN
                ALTER TABLE {table_name}
                ALTER COLUMN {column_name}
                TYPE {to_type_sql}
                USING {using_sql};
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    for table_name, column_name in TIMEZONE_COLUMNS:
        _alter_column_type(
            table_name,
            column_name,
            "timestamp without time zone",
            "TIMESTAMPTZ",
            f"{column_name} AT TIME ZONE 'UTC'",
        )


def downgrade() -> None:
    for table_name, column_name in TIMEZONE_COLUMNS:
        _alter_column_type(
            table_name,
            column_name,
            "timestamp with time zone",
            "TIMESTAMP",
            f"{column_name} AT TIME ZONE 'UTC'",
        )
