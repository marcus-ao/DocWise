from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index(
        "ix_documents_provenance_source",
        "documents",
        [sa.text("(provenance->>'source')")],
        postgresql_using="btree",
    )
    op.add_column(
        "documents",
        sa.Column("parent_document_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_documents_parent_document_id",
        "documents",
        "documents",
        ["parent_document_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_documents_parent_id", "documents", ["parent_document_id"])
    op.add_column(
        "documents",
        sa.Column("is_container", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.execute("ALTER TYPE document_status ADD VALUE IF NOT EXISTS 'container'")


def downgrade() -> None:
    op.drop_index("ix_documents_parent_id", table_name="documents")
    op.drop_constraint("fk_documents_parent_document_id", "documents", type_="foreignkey")
    op.drop_column("documents", "parent_document_id")
    op.drop_column("documents", "is_container")
    op.drop_index("ix_documents_provenance_source", table_name="documents")
    op.drop_column("documents", "provenance")
    op.drop_column("documents", "metadata")
