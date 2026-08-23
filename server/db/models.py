"""SQLAlchemy models for the node canvas — design/merge-doc.md §3.

Three tables plus one operational-flags table. The backend never queries into
`Project.document`; it reads and writes the JSONB blob whole (§0.1, §5.1).
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


asset_type_enum = ENUM("image", "video", "audio", name="asset_type")
asset_status_enum = ENUM("pending", "ready", "failed", name="asset_status")
tx_status_enum = ENUM("queued", "running", "succeeded", "failed", name="tx_status")

# Opaque node_id format shared with the frontend's newNodeId() — see contracts/document.py (M2).
NODE_ID_PATTERN = r"^node_[a-zA-Z0-9_-]{12}$"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    owner_id: Mapped[str] = mapped_column(Text, nullable=False)  # Clerk subject
    title: Mapped[str] = mapped_column(Text, nullable=False, server_default="Untitled")
    document: Mapped[dict] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[object] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[object] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    transformation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # null for uploads
    type: Mapped[str] = mapped_column(asset_type_enum, nullable=False)
    status: Mapped[str] = mapped_column(asset_status_enum, nullable=False, server_default="pending")
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)  # R2 object key, never a URL
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[object] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("assets_project_idx", "project_id", text("created_at DESC")),
    )


class Transformation(Base):
    __tablename__ = "transformations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(Text, nullable=False)  # denormalized; per-user history
    node_id: Mapped[str | None] = mapped_column(Text)  # opaque; no FK, see §2.1.1 of the v0 spec
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    request: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(tx_status_enum, nullable=False, server_default="queued")
    provider_job_id: Mapped[str | None] = mapped_column(Text)
    error: Mapped[dict | None] = mapped_column(JSONB)
    provider_response: Mapped[dict | None] = mapped_column(JSONB)  # terminal payload, verbatim
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    retry_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transformations.id")
    )
    cost_credits: Mapped[int | None] = mapped_column(Integer)
    queued_at: Mapped[object] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[object | None] = mapped_column(TIMESTAMP(timezone=True))
    completed_at: Mapped[object | None] = mapped_column(TIMESTAMP(timezone=True))

    # Queue state. This table IS the queue; there is no external broker (§1, §7).
    visible_at: Mapped[object] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    lease_expires_at: Mapped[object | None] = mapped_column(TIMESTAMP(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    __table_args__ = (
        CheckConstraint(f"node_id ~ '{NODE_ID_PATTERN}'", name="ck_transformations_node_id_format"),
        UniqueConstraint("idempotency_key", name="uq_transformations_idempotency_key"),
        Index("tx_active_idx", "status", "started_at", postgresql_where=text("status in ('queued', 'running')")),
        Index("tx_user_recent_idx", "user_id", text("queued_at DESC")),
        Index("tx_claimable_idx", "visible_at", postgresql_where=text("status in ('queued', 'running')")),
        # One active generation per node, enforced by the database — see §3 of the v0 spec for
        # why an application-level SELECT-then-INSERT is not sufficient. NULL node_ids don't conflict.
        Index(
            "tx_one_active_per_node",
            "node_id",
            unique=True,
            postgresql_where=text("status in ('queued', 'running')"),
        ),
    )


class SystemFlag(Base):
    """Operational levers. One row, three columns; the 2am kill switch."""

    __tablename__ = "system_flags"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[object] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
