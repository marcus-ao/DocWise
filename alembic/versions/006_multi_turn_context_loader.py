from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("queries", sa.Column("context_summary", sa.Text(), nullable=True))
    op.add_column("agent_runs", sa.Column("turn_index", sa.Integer(), nullable=True))
    op.add_column(
        "agent_runs",
        sa.Column("parent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_agent_runs_parent_run_id",
        "agent_runs",
        "agent_runs",
        ["parent_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        """
        WITH ordered AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY query_id
                    ORDER BY created_at ASC, id ASC
                ) - 1 AS computed_turn_index,
                LAG(id) OVER (
                    PARTITION BY query_id
                    ORDER BY created_at ASC, id ASC
                ) AS computed_parent_run_id
            FROM agent_runs
        )
        UPDATE agent_runs AS ar
        SET
            turn_index = ordered.computed_turn_index,
            parent_run_id = ordered.computed_parent_run_id
        FROM ordered
        WHERE ar.id = ordered.id
          AND ar.turn_index IS NULL
        """
    )
    # Set NOT NULL together with a server_default so direct SQL INSERTs that omit
    # turn_index (e.g. data backfill jobs) still succeed. The ORM already has
    # server_default="0" on the column; this keeps the SQL schema consistent.
    op.alter_column(
        "agent_runs",
        "turn_index",
        nullable=False,
        server_default="0",
    )
    op.create_unique_constraint(
        "uq_agent_runs_query_turn",
        "agent_runs",
        ["query_id", "turn_index"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_agent_runs_query_turn", "agent_runs", type_="unique")
    op.drop_constraint("fk_agent_runs_parent_run_id", "agent_runs", type_="foreignkey")
    op.drop_column("agent_runs", "parent_run_id")
    op.drop_column("agent_runs", "turn_index")
    op.drop_column("queries", "context_summary")
