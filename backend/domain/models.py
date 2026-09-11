from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIM = 1024


class Base(DeclarativeBase):
    pass


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Workspace(Base, TimestampMixin):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    deployment_profile: Mapped[str] = mapped_column(String(32), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class Principal(Base, TimestampMixin):
    __tablename__ = "principals"

    id: Mapped[uuid.UUID] = uuid_pk()
    subject: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Membership(Base, TimestampMixin):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "principal_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    principal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"), nullable=False)
    roles: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    group_ids: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)

    workspace: Mapped[Workspace] = relationship()
    principal: Mapped[Principal] = relationship()


class Source(Base, TimestampMixin):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    authority_class: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_role: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    ingestion_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    allowed_groups: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Document(Base, TimestampMixin):
    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_workspace", "workspace_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    visibility: Mapped[str] = mapped_column(String(64), nullable=False)
    classification: Mapped[str] = mapped_column(String(64), default="internal")
    lifecycle_status: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(16), default="en")
    topic: Mapped[str | None] = mapped_column(String(128))
    allowed_groups: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    source: Mapped[Source] = relationship()
    versions: Mapped[list[DocumentVersion]] = relationship(back_populates="document")


class DocumentVersion(Base, TimestampMixin):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "revision"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), default="plaintext-1")
    approval_state: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    page_count: Mapped[int] = mapped_column(Integer, default=1)
    ocr_pages: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list)

    document: Mapped[Document] = relationship(back_populates="versions")
    chunks: Mapped[list[Chunk]] = relationship(back_populates="version")


class Chunk(Base, TimestampMixin):
    __tablename__ = "chunks"
    __table_args__ = (
        Index("ix_chunks_workspace", "workspace_id"),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), nullable=False)
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    heading_path: Mapped[str] = mapped_column(String(1000), default="")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page_start: Mapped[int] = mapped_column(Integer, default=1)
    page_end: Mapped[int] = mapped_column(Integer, default=1)
    table_ref: Mapped[str | None] = mapped_column(String(200))
    language: Mapped[str] = mapped_column(String(16), default="en")
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    tsv: Mapped[Any] = mapped_column(TSVECTOR, nullable=True)
    index_generation: Mapped[int] = mapped_column(Integer, default=1)

    version: Mapped[DocumentVersion] = relationship(back_populates="chunks")


class Product(Base, TimestampMixin):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("workspace_id", "sku"),
        Index("ix_products_workspace", "workspace_id"),
        Index("ix_products_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_products_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    sku: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    unit: Mapped[str] = mapped_column(String(32), default="each")
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    list_price: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"))
    visibility: Mapped[str] = mapped_column(String(64), default="public_workspace")
    location: Mapped[str] = mapped_column(String(128), default="global")
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    completeness: Mapped[float] = mapped_column(Numeric(6, 4), default=Decimal("1"))
    embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    tsv: Mapped[Any] = mapped_column(TSVECTOR, nullable=True)
    image_key: Mapped[str | None] = mapped_column(String(500))


class PriceObservation(Base, TimestampMixin):
    __tablename__ = "price_observations"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    tax_included: Mapped[bool] = mapped_column(Boolean, default=True)
    shipping_included: Mapped[bool] = mapped_column(Boolean, default=False)
    condition: Mapped[str] = mapped_column(String(32), default="new")
    pack_size: Mapped[int] = mapped_column(Integer, default=1)
    source_name: Mapped[str] = mapped_column(String(200), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    comparable: Mapped[bool] = mapped_column(Boolean, default=True)


class SpendRecord(Base, TimestampMixin):
    __tablename__ = "spend_records"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    supplier_id: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    source_revision: Mapped[int] = mapped_column(Integer, default=1)


class OrderRecord(Base, TimestampMixin):
    __tablename__ = "order_records"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    supplier_id: Mapped[str] = mapped_column(String(128), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    additional_service_amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"))
    ordered_at: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    source_revision: Mapped[int] = mapped_column(Integer, default=1)


class SourcingEvent(Base, TimestampMixin):
    __tablename__ = "sourcing_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    participant_count: Mapped[int] = mapped_column(Integer, nullable=False)
    participant_ids: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    winner_id: Mapped[str | None] = mapped_column(String(128))
    offer_amounts: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    submission_times: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome: Mapped[str] = mapped_column(String(64), default="awarded")
    revision: Mapped[int] = mapped_column(Integer, default=1)


class DetectionFinding(Base, TimestampMixin):
    __tablename__ = "detection_findings"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "entity_type",
            "entity_id",
            "detector_id",
            "detector_version",
            "entity_revision",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    entity_revision: Mapped[int] = mapped_column(Integer, default=1)
    detector_id: Mapped[str] = mapped_column(String(128), nullable=False)
    detector_version: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    reason: Mapped[str | None] = mapped_column(Text)


class Draft(Base, TimestampMixin):
    __tablename__ = "drafts"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    template_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"), nullable=False)
    current_revision_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    brief: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class DraftRevision(Base, TimestampMixin):
    __tablename__ = "draft_revisions"
    __table_args__ = (UniqueConstraint("draft_id", "revision"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    draft_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("drafts.id"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    unresolved_assumptions: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    state: Mapped[str] = mapped_column(String(32), nullable=False)


class ReviewDecision(Base, TimestampMixin):
    __tablename__ = "review_decisions"
    __table_args__ = (UniqueConstraint("revision_id", "reviewer_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    draft_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("drafts.id"), nullable=False)
    revision_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("draft_revisions.id"), nullable=False)
    revision_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    reviewer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="")


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "principal_id", "job_type", "idempotency_key"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    principal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"), nullable=False)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    progress: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    permission_fingerprint: Mapped[str] = mapped_column(String(128), default="")


class Interaction(Base, TimestampMixin):
    __tablename__ = "interactions"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    principal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    capability: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    request: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    response: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    execution_manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"))
    final_state: Mapped[str] = mapped_column(String(64), default="completed")


class Feedback(Base, TimestampMixin):
    __tablename__ = "feedback"
    __table_args__ = (UniqueConstraint("workspace_id", "idempotency_key"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    principal_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("principals.id"), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    comment: Mapped[str] = mapped_column(Text, default="")
    disposition: Mapped[str] = mapped_column(String(64), default="submitted")
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)


class EvaluationCase(Base, TimestampMixin):
    __tablename__ = "evaluation_cases"

    id: Mapped[uuid.UUID] = uuid_pk()
    dataset: Mapped[str] = mapped_column(String(128), nullable=False)
    split: Mapped[str] = mapped_column(String(32), nullable=False)
    capability: Mapped[str] = mapped_column(String(64), nullable=False)
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    expected: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)


class EvaluationRun(Base, TimestampMixin):
    __tablename__ = "evaluation_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    dataset: Mapped[str] = mapped_column(String(128), nullable=False)
    model_manifest: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    results: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class OutboxEvent(Base, TimestampMixin):
    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base, TimestampMixin):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    principal_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("principals.id"))
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    authorized: Mapped[bool] = mapped_column(Boolean, default=True)


WORKSPACE_TABLES = [
    Source,
    Document,
    DocumentVersion,
    Chunk,
    Product,
    PriceObservation,
    SpendRecord,
    OrderRecord,
    SourcingEvent,
    DetectionFinding,
    Draft,
    DraftRevision,
    ReviewDecision,
    Job,
    Interaction,
    Feedback,
    OutboxEvent,
    AuditEvent,
    Membership,
]
