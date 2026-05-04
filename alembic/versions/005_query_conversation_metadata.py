"""Add conversation metadata columns for query history management."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("queries", sa.Column("conversation_title", sa.String(length=256), nullable=True))
    op.add_column(
        "queries",
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.execute("UPDATE queries SET conversation_title = original_query WHERE conversation_title IS NULL")
    op.alter_column("queries", "is_archived", server_default=None)


def downgrade() -> None:
    op.drop_column("queries", "is_archived")
    op.drop_column("queries", "conversation_title")
