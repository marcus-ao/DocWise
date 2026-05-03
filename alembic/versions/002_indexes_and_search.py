"""indexes and search helpers

Revision ID: 002
Revises: 001
Create Date: 2026-05-01
"""
from __future__ import annotations

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE document_chunks
        SET content_tsv = to_tsvector('english', coalesce(content, ''))
        WHERE content_tsv IS NULL
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_document_chunks_content_tsv ON document_chunks USING GIN (content_tsv)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_document_chunks_active_workspace ON document_chunks (workspace_id, is_active)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_active_workspace")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_content_tsv")

