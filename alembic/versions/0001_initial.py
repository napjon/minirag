# ruff: noqa: E501
"""Initial schema matching backend.domain.models.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-10

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WORKSPACE_RLS_TABLES = [
    "sources",
    "documents",
    "document_versions",
    "chunks",
    "products",
    "price_observations",
    "spend_records",
    "order_records",
    "sourcing_events",
    "detection_findings",
    "drafts",
    "draft_revisions",
    "review_decisions",
    "jobs",
    "interactions",
    "feedback",
    "outbox_events",
    "audit_events",
    "memberships",
]


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("deployment_profile", sa.String(32), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "principals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("subject", sa.String(200), nullable=False, unique=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(200), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("principals.id"), nullable=False),
        sa.Column("roles", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("group_ids", postgresql.ARRAY(sa.String()), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("workspace_id", "principal_id"),
    )
    op.create_table(
        "sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("authority_class", sa.String(64), nullable=False),
        sa.Column("owner_role", sa.String(64), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("ingestion_policy", postgresql.JSONB(), nullable=False),
        sa.Column("allowed_groups", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("visibility", sa.String(64), nullable=False),
        sa.Column("classification", sa.String(64), nullable=False),
        sa.Column("lifecycle_status", sa.String(64), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("topic", sa.String(128), nullable=True),
        sa.Column("allowed_groups", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_documents_workspace", "documents", ["workspace_id"])
    op.create_table(
        "document_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("object_key", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=False),
        sa.Column("approval_state", sa.String(64), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("ocr_pages", postgresql.ARRAY(sa.Integer()), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("document_id", "revision"),
    )
    op.create_table(
        "chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("document_versions.id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("heading_path", sa.String(1000), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("table_ref", sa.String(200), nullable=True),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("tsv", postgresql.TSVECTOR(), nullable=True),
        sa.Column("index_generation", sa.Integer(), nullable=False),
        *_timestamps(),
    )
    op.create_index("ix_chunks_workspace", "chunks", ["workspace_id"])
    op.create_index("ix_chunks_tsv", "chunks", ["tsv"], postgresql_using="gin")
    op.create_index(
        "ix_chunks_embedding_hnsw",
        "chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("sku", sa.String(128), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(128), nullable=False),
        sa.Column("attributes", postgresql.JSONB(), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("list_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("visibility", sa.String(64), nullable=False),
        sa.Column("location", sa.String(128), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("completeness", sa.Numeric(6, 4), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("tsv", postgresql.TSVECTOR(), nullable=True),
        sa.Column("image_key", sa.String(500), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("workspace_id", "sku"),
    )
    op.create_index("ix_products_workspace", "products", ["workspace_id"])
    op.create_index("ix_products_tsv", "products", ["tsv"], postgresql_using="gin")
    op.create_index(
        "ix_products_embedding_hnsw",
        "products",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_table(
        "price_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("tax_included", sa.Boolean(), nullable=False),
        sa.Column("shipping_included", sa.Boolean(), nullable=False),
        sa.Column("condition", sa.String(32), nullable=False),
        sa.Column("pack_size", sa.Integer(), nullable=False),
        sa.Column("source_name", sa.String(200), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("comparable", sa.Boolean(), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "spend_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("category", sa.String(128), nullable=False),
        sa.Column("supplier_id", sa.String(128), nullable=False),
        sa.Column("amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "order_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("category", sa.String(128), nullable=False),
        sa.Column("supplier_id", sa.String(128), nullable=False),
        sa.Column("amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("additional_service_amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("ordered_at", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "sourcing_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("category", sa.String(128), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("participant_count", sa.Integer(), nullable=False),
        sa.Column("participant_ids", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("winner_id", sa.String(128), nullable=True),
        sa.Column("offer_amounts", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("submission_times", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "detection_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_revision", sa.Integer(), nullable=False),
        sa.Column("detector_id", sa.String(128), nullable=False),
        sa.Column("detector_version", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("principals.id"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint(
            "workspace_id",
            "entity_type",
            "entity_id",
            "detector_id",
            "detector_version",
            "entity_revision",
        ),
    )
    op.create_table(
        "drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("template_kind", sa.String(64), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("principals.id"), nullable=False),
        sa.Column("current_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("brief", postgresql.JSONB(), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "draft_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("drafts.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("evidence_ids", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("unresolved_assumptions", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("draft_id", "revision"),
    )
    op.create_table(
        "review_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("drafts.id"), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("draft_revisions.id"), nullable=False),
        sa.Column("revision_hash", sa.String(128), nullable=False),
        sa.Column("reviewer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("principals.id"), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("revision_id", "reviewer_id"),
    )
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("principals.id"), nullable=False),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("progress", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("permission_fingerprint", sa.String(128), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("workspace_id", "principal_id", "job_type", "idempotency_key"),
    )
    op.create_table(
        "interactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("principals.id"), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False, unique=True),
        sa.Column("capability", sa.String(64), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("request", postgresql.JSONB(), nullable=False),
        sa.Column("response", postgresql.JSONB(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("execution_manifest", postgresql.JSONB(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("final_state", sa.String(64), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("principals.id"), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.String(64), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("disposition", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("workspace_id", "idempotency_key"),
    )
    op.create_table(
        "evaluation_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("dataset", sa.String(128), nullable=False),
        sa.Column("split", sa.String(32), nullable=False),
        sa.Column("capability", sa.String(64), nullable=False),
        sa.Column("input", postgresql.JSONB(), nullable=False),
        sa.Column("expected", postgresql.JSONB(), nullable=False),
        sa.Column("tags", postgresql.ARRAY(sa.String()), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "evaluation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("dataset", sa.String(128), nullable=False),
        sa.Column("model_manifest", postgresql.JSONB(), nullable=False),
        sa.Column("results", postgresql.JSONB(), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("principal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("principals.id"), nullable=True),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(64), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.Column("authorized", sa.Boolean(), nullable=False),
        *_timestamps(),
    )

    tables = ", ".join(f"'{name}'" for name in WORKSPACE_RLS_TABLES)
    op.execute(
        sa.text(
            f"""
            DO $$
            DECLARE t text;
            BEGIN
              FOR t IN
                SELECT unnest(ARRAY[{tables}])
              LOOP
                EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
                EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
                EXECUTE format(
                  'DROP POLICY IF EXISTS workspace_isolation ON %I', t
                );
                EXECUTE format(
                  'CREATE POLICY workspace_isolation ON %I
                   USING (workspace_id = NULLIF(current_setting(''app.workspace_id'', true), '''')::uuid)
                   WITH CHECK (workspace_id = NULLIF(current_setting(''app.workspace_id'', true), '''')::uuid)',
                  t
                );
              END LOOP;
            END $$;
            """
        )
    )


def downgrade() -> None:
    for name in (
        "audit_events",
        "outbox_events",
        "evaluation_runs",
        "evaluation_cases",
        "feedback",
        "interactions",
        "jobs",
        "review_decisions",
        "draft_revisions",
        "drafts",
        "detection_findings",
        "sourcing_events",
        "order_records",
        "spend_records",
        "price_observations",
        "products",
        "chunks",
        "document_versions",
        "documents",
        "sources",
        "memberships",
        "principals",
        "workspaces",
    ):
        op.drop_table(name)
