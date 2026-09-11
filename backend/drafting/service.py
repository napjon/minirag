from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.security import AuthContext
from backend.domain.enums import DraftState, Role, TemplateKind
from backend.domain.models import Draft, DraftRevision, ReviewDecision
from backend.model_gateway.base import ModelGateway
from backend.retrieval.service import RetrievalService

TEMPLATES: dict[str, list[str]] = {
    TemplateKind.EQUIPMENT_REQUIREMENTS.value: [
        "Purpose",
        "Requirements",
        "Quantities",
        "Acceptance",
    ],
    TemplateKind.MAINTENANCE_SERVICE.value: ["Purpose", "Scope", "Service levels", "Acceptance"],
    TemplateKind.INSTALLATION_WORK.value: [
        "Purpose",
        "Site constraints",
        "Work description",
        "Acceptance",
    ],
    TemplateKind.RECURRING_SERVICE.value: ["Purpose", "Coverage", "Exclusions", "Acceptance"],
}

MANDATORY_BRIEF = ["purpose", "quantities", "delivery_constraints", "acceptance"]


class DraftingService:
    def __init__(self, db: AsyncSession, gateway: ModelGateway):
        self.db = db
        self.gateway = gateway

    async def create(
        self, auth: AuthContext, *, template_kind: str, title: str, brief: dict[str, Any]
    ) -> Draft:
        if template_kind not in TEMPLATES:
            raise ValueError("unsupported draft template")
        missing = [field for field in MANDATORY_BRIEF if not brief.get(field)]
        unresolved = [f"Missing mandatory field: {field}" for field in missing]
        retrieval = RetrievalService(self.db, self.gateway)
        evidence = await retrieval.search(auth, brief.get("purpose") or title, evidence_k=5)
        evidence_block = [
            {
                "evidence_id": str(item["chunk_id"]),
                "text": item.get("text") or item.get("supporting_span"),
                "section": item.get("section_path"),
            }
            for item in evidence
        ]
        generation = await self.gateway.generate(
            "DRAFT_JSON "
            + json.dumps(
                {"template": template_kind, "brief": brief, "evidence": evidence_block},
                default=str,
            ),
            json_schema={"type": "object"},
        )
        structured = generation.structured if isinstance(generation.structured, dict) else {}
        sections = [
            section
            for section in (structured.get("sections") or [])
            if isinstance(section, dict) and isinstance(section.get("heading"), str)
        ]
        required = TEMPLATES[template_kind]
        allowed_evidence_ids = {str(item["chunk_id"]) for item in evidence}
        by_heading = {s.get("heading"): s for s in sections}
        raw_assumptions = structured.get("unresolved_assumptions")
        model_assumptions = (
            [str(item) for item in raw_assumptions] if isinstance(raw_assumptions, list) else []
        )
        filled = []
        for heading in required:
            raw_section = by_heading.get(heading) or {
                "heading": heading,
                "body": brief.get(heading.lower(), "[unknown — do not invent]"),
                "evidence_ids": [],
            }
            body = raw_section.get("body")
            if not isinstance(body, str):
                body = str(brief.get(heading.lower()) or "[unknown — do not invent]")
            raw_ids = raw_section.get("evidence_ids")
            evidence_ids = (
                [str(item) for item in raw_ids if str(item) in allowed_evidence_ids]
                if isinstance(raw_ids, list)
                else []
            )
            section = {"heading": heading, "body": body, "evidence_ids": evidence_ids}
            if heading == "Purpose" and evidence:
                section["body"] = (
                    evidence[0].get("text") or evidence[0].get("supporting_span") or section["body"]
                )
                section["evidence_ids"] = [str(evidence[0]["chunk_id"])]
            filled.append(section)
        content = {
            "template_kind": template_kind,
            "brief": brief,
            "sections": filled,
            "evidence": evidence_block,
            "unresolved_assumptions": unresolved + model_assumptions,
        }
        raw = json.dumps(content, sort_keys=True)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        draft = Draft(
            workspace_id=auth.workspace_id,
            template_kind=template_kind,
            title=title,
            author_id=auth.principal_id,
            state=DraftState.AWAITING_REVIEW.value,
            brief=brief,
        )
        self.db.add(draft)
        await self.db.flush()
        revision = DraftRevision(
            workspace_id=auth.workspace_id,
            draft_id=draft.id,
            revision=1,
            content_hash=digest,
            content=content,
            evidence_ids=[str(item["chunk_id"]) for item in evidence],
            unresolved_assumptions=content["unresolved_assumptions"],
            state=DraftState.AWAITING_REVIEW.value,
        )
        self.db.add(revision)
        await self.db.flush()
        draft.current_revision_id = revision.id
        return draft

    async def list_drafts(
        self, auth: AuthContext, *, state: str | None = None
    ) -> list[dict[str, Any]]:
        stmt = (
            select(Draft, DraftRevision)
            .outerjoin(DraftRevision, DraftRevision.id == Draft.current_revision_id)
            .where(Draft.workspace_id == auth.workspace_id)
        )
        if Role.ADMIN not in auth.roles:
            if Role.REVIEWER in auth.roles:
                stmt = stmt.where(Draft.state == (state or DraftState.AWAITING_REVIEW.value))
            else:
                stmt = stmt.where(Draft.author_id == auth.principal_id)
                if state:
                    stmt = stmt.where(Draft.state == state)
        elif state:
            stmt = stmt.where(Draft.state == state)
        stmt = stmt.order_by(Draft.created_at.desc()).limit(50)
        rows = (await self.db.execute(stmt)).all()
        items = []
        for draft, revision in rows:
            items.append(
                {
                    "id": draft.id,
                    "title": draft.title,
                    "state": draft.state,
                    "author_id": draft.author_id,
                    "revision_hash": revision.content_hash if revision else None,
                }
            )
        return items

    async def review(
        self, auth: AuthContext, draft_id: UUID, *, decision: str, reason: str, revision_hash: str
    ) -> Draft:
        if decision not in {"approved", "rejected"}:
            raise ValueError("invalid review decision")
        # Serialize review decisions for one draft so two reviewers cannot both
        # approve a stale awaiting-review state concurrently.
        draft = await self.db.scalar(select(Draft).where(Draft.id == draft_id).with_for_update())
        if draft is None or draft.workspace_id != auth.workspace_id:
            raise ValueError("draft not found")
        if draft.author_id == auth.principal_id:
            raise PermissionError("authors cannot approve their own drafts")
        revision = await self.db.get(DraftRevision, draft.current_revision_id)
        if (
            revision is None
            or revision.workspace_id != auth.workspace_id
            or revision.draft_id != draft.id
            or revision.content_hash != revision_hash
        ):
            raise ValueError("revision hash mismatch")
        if draft.state != DraftState.AWAITING_REVIEW.value:
            raise ValueError("draft is not awaiting review")
        if decision == "approved":
            revision.state = DraftState.APPROVED.value
            draft.state = DraftState.APPROVED.value
        else:
            revision.state = DraftState.REJECTED.value
            draft.state = DraftState.REJECTED.value
        self.db.add(
            ReviewDecision(
                workspace_id=auth.workspace_id,
                draft_id=draft.id,
                revision_id=revision.id,
                revision_hash=revision_hash,
                reviewer_id=auth.principal_id,
                decision=decision,
                reason=reason,
            )
        )
        await self.db.flush()
        return draft

    async def export(self, auth: AuthContext, draft_id: UUID) -> dict[str, Any]:
        draft = await self.db.get(Draft, draft_id)
        if draft is None or draft.workspace_id != auth.workspace_id:
            raise ValueError("draft not found")
        if draft.state != DraftState.APPROVED.value:
            raise PermissionError("final export requires an approved revision")
        revision = await self.db.get(DraftRevision, draft.current_revision_id)
        if (
            revision is None
            or revision.workspace_id != auth.workspace_id
            or revision.draft_id != draft.id
            or revision.state != DraftState.APPROVED.value
        ):
            raise PermissionError("final export requires an approved revision")
        return {
            "draft_id": str(draft.id),
            "revision_hash": revision.content_hash,
            "title": draft.title,
            "content": revision.content,
        }
