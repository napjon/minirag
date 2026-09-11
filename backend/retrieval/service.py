from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from backend.auth.security import AuthContext
from backend.auth.visibility import can_read_document
from backend.domain.enums import LifecycleStatus
from backend.domain.models import Chunk, Document, DocumentVersion
from backend.model_gateway.base import ModelGateway
from backend.retrieval.evidence import supporting_span


def rrf_fuse(lists: list[list[uuid.UUID]], k: int = 60) -> list[uuid.UUID]:
    scores: dict[uuid.UUID, float] = {}
    for ranked in lists:
        for rank, item in enumerate(ranked, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return [item for item, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)]


class RetrievalService:
    def __init__(self, db: AsyncSession, gateway: ModelGateway):
        self.db = db
        self.gateway = gateway

    def _visible_filter(self, auth: AuthContext):
        from backend.domain.enums import Role, Visibility

        clauses = [Document.workspace_id == auth.workspace_id]
        clauses.append(Document.lifecycle_status == LifecycleStatus.PUBLISHED.value)
        if Role.ADMIN in auth.roles or Role.REVIEWER in auth.roles:
            return clauses
        public = Document.visibility == Visibility.PUBLIC_WORKSPACE.value
        if auth.group_ids:
            restricted = (
                Document.visibility == Visibility.RESTRICTED.value
            ) & Document.allowed_groups.overlap(list(auth.group_ids))
            clauses.append(or_(public, restricted))
        else:
            clauses.append(public)
        return clauses

    def _apply_version_window(self, stmt, as_of: date | None):
        stmt = stmt.where(DocumentVersion.document_id == Document.id)
        if as_of is None:
            return stmt.where(Document.current_version_id == Chunk.version_id)
        effective = aliased(DocumentVersion)
        effective_revision = (
            select(func.max(effective.revision))
            .where(effective.document_id == Document.id)
            .where(effective.approval_state == "approved")
            .where(or_(effective.effective_from.is_(None), effective.effective_from <= as_of))
            .where(or_(effective.effective_to.is_(None), effective.effective_to >= as_of))
            .correlate(Document)
            .scalar_subquery()
        )
        return (
            stmt.where(
                or_(
                    DocumentVersion.effective_from.is_(None),
                    DocumentVersion.effective_from <= as_of,
                )
            )
            .where(
                or_(
                    DocumentVersion.effective_to.is_(None),
                    DocumentVersion.effective_to >= as_of,
                )
            )
            .where(DocumentVersion.revision == effective_revision)
        )

    async def search(
        self,
        auth: AuthContext,
        query: str,
        *,
        as_of: date | None = None,
        lexical_k: int = 60,
        vector_k: int = 60,
        rerank_k: int = 40,
        evidence_k: int = 10,
    ) -> list[dict[str, Any]]:
        [embedding] = await self.gateway.embed([query])
        filters = self._visible_filter(auth)
        tsq = func.plainto_tsquery("simple", query)
        first_term = query.split()[0] if query.split() else query
        lexical_stmt = (
            self._apply_version_window(
                select(Chunk.id)
                .join(Document, Document.id == Chunk.document_id)
                .join(DocumentVersion, DocumentVersion.id == Chunk.version_id)
                .where(*filters)
                .where(DocumentVersion.approval_state == "approved")
                .where(or_(Chunk.tsv.op("@@")(tsq), Chunk.text.ilike(f"%{first_term}%"))),
                as_of,
            )
            .order_by(func.ts_rank_cd(Chunk.tsv, tsq).desc())
            .limit(lexical_k)
        )
        lexical_ids = list((await self.db.scalars(lexical_stmt)).all())

        vector_stmt = self._apply_version_window(
            select(Chunk.id, Chunk.embedding)
            .join(Document, Document.id == Chunk.document_id)
            .join(DocumentVersion, DocumentVersion.id == Chunk.version_id)
            .where(*filters)
            .where(DocumentVersion.approval_state == "approved")
            .where(Chunk.embedding.is_not(None)),
            as_of,
        )
        distance = Chunk.embedding.cosine_distance(embedding)
        vector_stmt = vector_stmt.order_by(distance).limit(vector_k)
        vector_ids = [chunk_id for chunk_id, _stored in (await self.db.execute(vector_stmt)).all()]
        fused = rrf_fuse([lexical_ids, vector_ids])[:rerank_k]
        if not fused:
            return []
        rows = (
            await self.db.execute(
                select(Chunk, Document, DocumentVersion)
                .join(Document, Document.id == Chunk.document_id)
                .join(DocumentVersion, DocumentVersion.id == Chunk.version_id)
                .where(Chunk.id.in_(fused))
            )
        ).all()
        # Canonical recheck: published, approved, workspace, visibility.
        authorized = []
        for chunk, document, version in rows:
            if document.workspace_id != auth.workspace_id:
                continue
            if version.workspace_id != auth.workspace_id or version.document_id != document.id:
                continue
            if document.lifecycle_status != LifecycleStatus.PUBLISHED.value:
                continue
            if version.approval_state != "approved":
                continue
            if as_of is None:
                if document.current_version_id != version.id:
                    continue
            else:
                if version.effective_from is not None and version.effective_from > as_of:
                    continue
                if version.effective_to is not None and version.effective_to < as_of:
                    continue
            if not can_read_document(
                auth,
                visibility=document.visibility,
                allowed_groups=document.allowed_groups,
                lifecycle_status=document.lifecycle_status,
            ):
                continue
            authorized.append((chunk, document, version))
        passages = [chunk.text for chunk, _, _ in authorized]
        scores = await self.gateway.rerank(query, passages) if passages else []
        ranked = sorted(
            zip(authorized, scores or [0.0] * len(authorized), strict=False),
            key=lambda item: item[1],
            reverse=True,
        )[:evidence_k]
        evidence = []
        for (chunk, document, version), score in ranked:
            span = supporting_span(chunk.text, query)
            evidence.append(
                {
                    "document_id": document.id,
                    "document_version_id": version.id,
                    "chunk_id": chunk.id,
                    "section_path": chunk.heading_path,
                    "page_or_table_location": f"p.{chunk.page_start}",
                    "supporting_span": span,
                    "source_effective_date": version.effective_from,
                    "authorized_viewer_url": f"/v1/documents/{document.id}",
                    "text": chunk.text,
                    "score": float(score),
                    "title": document.title,
                }
            )
        return evidence
