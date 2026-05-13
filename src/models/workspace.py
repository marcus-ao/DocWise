from uuid import UUID, uuid4

from sqlalchemy import Boolean, Enum, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, TimestampMixin, WorkspaceType


class Workspace(TimestampMixin, Base):
    __tablename__ = "workspaces"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    workspace_type: Mapped[WorkspaceType] = mapped_column(
        Enum(WorkspaceType, name="workspace_type"), nullable=False
    )
    project_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    # Workspace lookups are part of hot routing paths and should not eagerly
    # hydrate the full document set for each workspace.
    documents = relationship("Document", back_populates="workspace", lazy="select")
