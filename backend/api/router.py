from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import backend.observability  # noqa: F401
from backend.analytics.service import AnalyticsService
from backend.auth.security import (
    CAPABILITIES,
    AuthContext,
    _membership_groups,
    get_auth,
    get_db,
    issue_token,
    require,
)
from backend.auth.visibility import can_read_document, can_read_product
from backend.catalog.service import CatalogService
from backend.config import Settings, get_settings
from backend.db import apply_rls
from backend.detection.service import DetectionService
from backend.domain.audit import record_audit_event, record_interaction
from backend.domain.enums import JobState, JobType, Role, Visibility
from backend.domain.models import (
    AuditEvent,
    Document,
    Feedback,
    Interaction,
    Principal,
    Product,
    Source,
    SourcingEvent,
    Workspace,
)
from backend.domain.schemas import (
    AnalyticsQueryRequest,
    DemoLoginRequest,
    DraftCreateRequest,
    DraftReviewRequest,
    Envelope,
    FeedbackRequest,
    ListingCheckRequest,
    ProductCompareRequest,
    ProductSearchRequest,
    QuestionRequest,
    SourceCreateRequest,
    SourcingEvalRequest,
    TokenResponse,
)
from backend.drafting.service import DraftingService
from backend.ingestion.service import IngestionService
from backend.jobs.service import IdempotencyConflict, JobService
from backend.model_gateway.base import get_gateway
from backend.workflows.qa import answer_question

router = APIRouter()


def _jsonable(value):
    return json.loads(json.dumps(value, default=str))


def envelope(
    request_id: str, status_value: str, result, evidence=None, warnings=None, manifest_id=None
):
    return Envelope(
        request_id=request_id,
        status=status_value,
        result=result,
        evidence=evidence or [],
        warnings=warnings or [],
        execution_manifest_id=manifest_id,
    )


@router.get("/health")
async def health(settings: Settings = Depends(get_settings)):
    return {
        "ok": True,
        "profile": settings.deployment_profile,
        "provider": settings.model_provider,
        "egress_blocked": settings.private_egress_blocked,
    }


@router.get("/v1/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.post("/v1/auth/demo", response_model=TokenResponse)
async def demo_login(
    body: DemoLoginRequest,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if settings.auth_mode != "demo":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "demo auth disabled")
    principal = await db.scalar(select(Principal).where(Principal.email == body.email))
    workspace = await db.scalar(select(Workspace).where(Workspace.slug == body.workspace))
    if principal is None or workspace is None or not principal.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown demo identity")
    from backend.domain.models import Membership

    await apply_rls(db, str(workspace.id), str(principal.id))
    membership = await db.scalar(
        select(Membership).where(
            Membership.principal_id == principal.id, Membership.workspace_id == workspace.id
        )
    )
    if membership is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no membership")
    try:
        roles = [Role(r) for r in membership.roles]
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "invalid membership configuration"
        ) from exc
    token = issue_token(
        settings=settings,
        principal=principal,
        workspace=workspace,
        roles=roles,
        group_ids=list(_membership_groups(membership.group_ids)),
    )
    return TokenResponse(
        access_token=token,
        workspace_id=workspace.id,
        principal_id=principal.id,
        roles=roles,
        display_name=principal.display_name,
    )


@router.get("/v1/me")
async def me(auth: AuthContext = Depends(get_auth)):
    return {
        "principal_id": auth.principal_id,
        "workspace_id": auth.workspace_id,
        "email": auth.email,
        "display_name": auth.display_name,
        "roles": [r.value for r in auth.roles],
        "groups": list(auth.group_ids),
        "capabilities": sorted(capability for capability in CAPABILITIES if auth.can(capability)),
    }


@router.post("/v1/questions")
async def questions(
    body: QuestionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require("questions")),
    settings: Settings = Depends(get_settings),
):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    result, evidence, manifest = await answer_question(
        db=db,
        auth=auth,
        gateway=get_gateway(settings),
        settings=settings,
        request_id=request_id,
        question=body.question,
        language=body.language,
        as_of=body.as_of,
    )
    await db.commit()
    return envelope(request_id, result.status.value, result, evidence=evidence)


@router.post("/v1/analytics/queries")
async def analytics_queries(
    body: AnalyticsQueryRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require("analytics")),
    settings: Settings = Depends(get_settings),
):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    service = AnalyticsService(db, get_gateway(settings))
    try:
        if body.pattern is None:
            if not body.question:
                raise ValueError("pattern or question is required")
            intent = await service.parse_intent(body.question)
        else:
            intent = {
                "pattern": body.pattern.value,
                "filters": body.filters,
                "group_by": body.group_by,
                "presentation": body.presentation,
            }
        result = await service.execute(
            auth, pattern=intent["pattern"], filters=intent["filters"], group_by=intent["group_by"]
        )
        result["presentation"] = intent["presentation"]
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    record_interaction(
        db,
        auth,
        request_id=request_id,
        capability="analytics",
        status="answered",
        request={"pattern": result.get("pattern"), "filters": result.get("filters")},
        response=_jsonable(result),
    )
    await db.commit()
    return envelope(request_id, "answered", result)


@router.post("/v1/products/search")
async def product_search(
    body: ProductSearchRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require("products.search")),
    settings: Settings = Depends(get_settings),
):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    items = await CatalogService(db, get_gateway(settings)).search(
        auth,
        query=body.query,
        category=body.category,
        min_price=body.min_price,
        max_price=body.max_price,
        location=body.location,
        available_only=body.available_only,
        attributes=body.attributes,
        preferences=body.preferences,
        limit=body.limit,
    )
    record_interaction(
        db,
        auth,
        request_id=request_id,
        capability="products.search",
        status="answered",
        request={"query": body.query, "category": body.category},
        response=_jsonable({"items": items}),
    )
    await db.commit()
    return envelope(request_id, "answered", {"items": items})


@router.post("/v1/products/compare")
async def product_compare(
    body: ProductCompareRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require("products.compare")),
    settings: Settings = Depends(get_settings),
):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    result = await CatalogService(db, get_gateway(settings)).compare(auth, body.product_ids)
    record_interaction(
        db,
        auth,
        request_id=request_id,
        capability="products.compare",
        status="answered",
        request={"product_ids": [str(product_id) for product_id in body.product_ids]},
        response=_jsonable(result),
    )
    await db.commit()
    return envelope(request_id, "answered", result)


@router.get("/v1/products/{product_id}/references")
async def product_references(
    product_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require("products.references")),
    settings: Settings = Depends(get_settings),
):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    result = await CatalogService(db, get_gateway(settings)).references(auth, product_id)
    status_value = result.get("status", "answered")
    record_interaction(
        db,
        auth,
        request_id=request_id,
        capability="products.references",
        status=status_value,
        request={"product_id": str(product_id)},
        response=_jsonable(result),
    )
    await db.commit()
    return envelope(request_id, status_value, result)


@router.post("/v1/listing-checks")
async def listing_checks(
    body: ListingCheckRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require("listing_checks")),
):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    findings = await DetectionService(db).listing_checks(
        auth, body.product_id, idempotency_key=body.idempotency_key
    )
    payload = [
        {
            "id": f.id,
            "detector_id": f.detector_id,
            "detector_version": f.detector_version,
            "severity": f.severity,
            "state": f.state,
            "explanation": f.explanation,
            "evidence": f.evidence,
        }
        for f in findings
    ]
    record_interaction(
        db,
        auth,
        request_id=request_id,
        capability="listing_checks",
        status="answered",
        request={"product_id": str(body.product_id)},
        response=_jsonable(payload),
    )
    await db.commit()
    return envelope(request_id, "answered", payload)


@router.post("/v1/sourcing-evaluations")
async def sourcing_evaluations(
    body: SourcingEvalRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require("sourcing")),
):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    findings = await DetectionService(db).sourcing_eval(
        auth, body.event_id, idempotency_key=body.idempotency_key
    )
    payload = [
        {
            "id": f.id,
            "detector_id": f.detector_id,
            "detector_version": f.detector_version,
            "severity": f.severity,
            "state": f.state,
            "explanation": f.explanation,
            "evidence": f.evidence,
        }
        for f in findings
    ]
    record_interaction(
        db,
        auth,
        request_id=request_id,
        capability="sourcing",
        status="answered",
        request={"event_id": str(body.event_id)},
        response=_jsonable(payload),
    )
    await db.commit()
    return envelope(request_id, "answered", payload)


@router.get("/v1/findings/{finding_id}")
async def get_finding(
    finding_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth),
):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    finding = await DetectionService(db).get(auth, finding_id)
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "finding not found")
    capability = "listing_checks" if finding.entity_type == "product" else "sourcing"
    if not auth.can(capability):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"missing capability {capability}")
    return envelope(
        request_id,
        "answered",
        {
            "id": finding.id,
            "detector_id": finding.detector_id,
            "detector_version": finding.detector_version,
            "severity": finding.severity,
            "state": finding.state,
            "explanation": finding.explanation,
            "evidence": finding.evidence,
            "entity_type": finding.entity_type,
            "entity_id": finding.entity_id,
        },
    )


@router.post("/v1/drafts", status_code=202)
async def create_draft(
    body: DraftCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require("drafts.create")),
    settings: Settings = Depends(get_settings),
):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    jobs = JobService(db)
    try:
        job = await jobs.create_or_get(
            auth,
            job_type=JobType.DRAFT.value,
            idempotency_key=body.idempotency_key,
            progress={
                "stage": "queued",
                "payload": {
                    "template_kind": body.template_kind.value,
                    "title": body.title,
                    "brief": body.brief,
                },
            },
        )
    except IdempotencyConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    async def _run(_job):
        draft = await DraftingService(db, get_gateway(settings)).create(
            auth, template_kind=body.template_kind.value, title=body.title, brief=body.brief
        )
        return {"draft_id": str(draft.id), "state": draft.state}

    try:
        if settings.job_execution_mode == "inline" and job.state != JobState.SUCCEEDED.value:
            await jobs.run(job, _run)
        status_value = "failed" if job.state == JobState.FAILED.value else "accepted"
        record_interaction(
            db,
            auth,
            request_id=request_id,
            capability="drafts.create",
            status=status_value,
            request={"title": body.title, "template_kind": body.template_kind.value},
            response=_jsonable({"job_id": job.id, "result": job.result, "error": job.error}),
            final_state=(
                "failed"
                if job.state == JobState.FAILED.value
                else "completed"
                if job.state == JobState.SUCCEEDED.value
                else "queued"
            ),
        )
        return envelope(
            request_id,
            status_value,
            {"job_id": job.id, "result": job.result, "error": job.error},
        )
    finally:
        await db.commit()


@router.post("/v1/drafts/{draft_id}/reviews")
async def review_draft(
    draft_id: uuid.UUID,
    body: DraftReviewRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require("drafts.review")),
    settings: Settings = Depends(get_settings),
):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    try:
        draft = await DraftingService(db, get_gateway(settings)).review(
            auth,
            draft_id,
            decision=body.decision,
            reason=body.reason,
            revision_hash=body.revision_hash,
        )
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except ValueError as exc:
        error_status = (
            status.HTTP_404_NOT_FOUND if str(exc) == "draft not found" else status.HTTP_409_CONFLICT
        )
        raise HTTPException(error_status, str(exc)) from exc
    record_interaction(
        db,
        auth,
        request_id=request_id,
        capability="drafts.review",
        status=draft.state,
        request={"draft_id": str(draft_id), "decision": body.decision},
        response={"draft_id": str(draft.id), "state": draft.state},
    )
    record_audit_event(
        db,
        auth,
        action="draft.reviewed",
        resource_type="draft",
        resource_id=str(draft.id),
        details={"decision": body.decision, "revision_hash": body.revision_hash},
    )
    await db.commit()
    return envelope(request_id, draft.state, {"draft_id": draft.id, "state": draft.state})


@router.post("/v1/drafts/{draft_id}/exports")
async def export_draft(
    draft_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require("drafts.export")),
    settings: Settings = Depends(get_settings),
):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    try:
        payload = await DraftingService(db, get_gateway(settings)).export(auth, draft_id)
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    record_interaction(
        db,
        auth,
        request_id=request_id,
        capability="drafts.export",
        status="answered",
        request={"draft_id": str(draft_id)},
        response=_jsonable(payload),
    )
    await db.commit()
    return envelope(request_id, "answered", payload)


@router.get("/v1/drafts")
async def list_drafts(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require("drafts.read")),
    settings: Settings = Depends(get_settings),
    state: str | None = Query(default=None),
):
    items = await DraftingService(db, get_gateway(settings)).list_drafts(auth, state=state)
    return {"items": items}


@router.get("/v1/drafts/{draft_id}")
async def get_draft(
    draft_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require("drafts.read")),
):
    from backend.domain.models import Draft, DraftRevision

    draft = await db.get(Draft, draft_id)
    if draft is None or draft.workspace_id != auth.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "draft not found")
    revision = await db.get(DraftRevision, draft.current_revision_id)
    if revision is not None and (
        revision.workspace_id != auth.workspace_id or revision.draft_id != draft.id
    ):
        revision = None
    return {
        "id": draft.id,
        "title": draft.title,
        "state": draft.state,
        "author_id": draft.author_id,
        "revision_hash": revision.content_hash if revision else None,
        "content": revision.content if revision else None,
        "evidence_ids": revision.evidence_ids if revision else [],
        "unresolved_assumptions": revision.unresolved_assumptions if revision else [],
    }


@router.post("/v1/feedback")
async def feedback(
    body: FeedbackRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require("feedback")),
):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    row = Feedback(
        workspace_id=auth.workspace_id,
        principal_id=auth.principal_id,
        target_type=body.target_type,
        target_id=body.target_id,
        label=body.label,
        comment=body.comment,
        idempotency_key=body.idempotency_key,
    )
    db.add(row)
    try:
        await db.flush()
        record_audit_event(
            db,
            auth,
            action="feedback.submitted",
            resource_type=body.target_type,
            resource_id=str(body.target_id),
            details={"label": body.label},
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "duplicate feedback") from exc
    return envelope(request_id, "accepted", {"id": row.id})


@router.get("/v1/jobs/{job_id}")
async def get_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(get_auth),
):
    job = await JobService(db).get(job_id, auth)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return {
        "id": job.id,
        "job_type": job.job_type,
        "state": job.state,
        "progress": job.progress,
        "result": job.result,
        "error": job.error,
    }


@router.get("/v1/documents/{document_id}")
async def get_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require("sources.read")),
):
    document = await db.get(Document, document_id)
    if document is None or document.workspace_id != auth.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "source not found")
    if not can_read_document(
        auth,
        visibility=document.visibility,
        allowed_groups=document.allowed_groups,
        lifecycle_status=document.lifecycle_status,
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "source not found")
    from backend.domain.models import DocumentVersion

    version = await db.get(DocumentVersion, document.current_version_id)
    if version is not None and (
        version.workspace_id != auth.workspace_id or version.document_id != document.id
    ):
        version = None
    return {
        "id": document.id,
        "title": document.title,
        "topic": document.topic,
        "status": document.lifecycle_status,
        "effective_from": version.effective_from if version else None,
        "text": version.extracted_text if version else "",
    }


@router.get("/v1/sources/{source_id}")
async def get_source(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require("sources.read")),
):
    source = await db.get(Source, source_id)
    if source is None or source.workspace_id != auth.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "source not found")
    elevated = Role.ADMIN in auth.roles or Role.REVIEWER in auth.roles
    allowed = set(source.allowed_groups or []) & set(auth.group_ids)
    if source.allowed_groups and not elevated and not allowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "source not found")
    return {
        "id": source.id,
        "name": source.name,
        "source_type": source.source_type,
        "authority_class": source.authority_class,
        "owner_role": source.owner_role,
        "is_active": source.is_active,
    }


@router.post("/v1/sources", status_code=201)
async def create_source(
    body: SourceCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require("sources.ingest")),
):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    source = Source(
        workspace_id=auth.workspace_id,
        source_type=body.source_type,
        authority_class=body.authority_class,
        owner_role=body.owner_role,
        name=body.name,
        ingestion_policy={},
        allowed_groups=body.allowed_groups,
        is_active=True,
    )
    db.add(source)
    await db.flush()
    record_audit_event(
        db,
        auth,
        action="source.created",
        resource_type="source",
        resource_id=str(source.id),
        details={"source_type": source.source_type, "authority_class": source.authority_class},
    )
    await db.commit()
    return envelope(request_id, "created", {"source_id": source.id, "name": source.name})


@router.post("/v1/documents/uploads", status_code=202)
async def upload_document(
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require("sources.ingest")),
    settings: Settings = Depends(get_settings),
    file: UploadFile = File(...),
    source_id: uuid.UUID = Form(...),
    title: str = Form(...),
    topic: str = Form("account-access"),
    language: str = Form("en"),
    idempotency_key: str = Form(...),
    publish: bool = Form(True),
):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    jobs = JobService(db)
    job = await jobs.create_or_get(
        auth, job_type=JobType.INGEST.value, idempotency_key=idempotency_key
    )

    async def _run(_job):
        payload = await file.read(settings.max_upload_bytes + 1)
        if len(payload) > settings.max_upload_bytes:
            raise ValueError(f"upload exceeds {settings.max_upload_bytes} byte limit")
        source = await db.get(Source, source_id)
        if source is None or source.workspace_id != auth.workspace_id:
            raise ValueError("source not found")
        document = await IngestionService(db, get_gateway(settings)).ingest_bytes(
            workspace_id=auth.workspace_id,
            source=source,
            title=title,
            body=payload,
            filename=file.filename or "upload.bin",
            topic=topic,
            language=language,
            publish=publish,
        )
        return {"document_id": str(document.id), "state": document.lifecycle_status}

    try:
        if job.state != JobState.SUCCEEDED.value:
            await jobs.run(job, _run)
        status_value = "accepted" if job.state == JobState.SUCCEEDED.value else "failed"
        record_interaction(
            db,
            auth,
            request_id=request_id,
            capability="sources.ingest",
            status=status_value,
            request={"title": title, "source_id": str(source_id)},
            response=_jsonable({"job_id": job.id, "result": job.result, "error": job.error}),
            final_state="completed" if job.state == JobState.SUCCEEDED.value else "failed",
        )
        record_audit_event(
            db,
            auth,
            action="document.ingested"
            if job.state == JobState.SUCCEEDED.value
            else "document.ingest_failed",
            resource_type="source",
            resource_id=str(source_id),
            details={"job_id": str(job.id), "title": title},
        )
        return envelope(
            request_id,
            "accepted" if job.state == JobState.SUCCEEDED.value else "failed",
            {"job_id": job.id, "result": job.result, "error": job.error},
        )
    finally:
        await db.commit()


@router.post("/v1/documents/{document_id}/withdraw")
async def withdraw_document(
    document_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require("sources.ingest")),
    settings: Settings = Depends(get_settings),
):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    document = await db.get(Document, document_id)
    if document is None or document.workspace_id != auth.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    await IngestionService(db, get_gateway(settings)).withdraw(document)
    record_interaction(
        db,
        auth,
        request_id=request_id,
        capability="sources.ingest",
        status="answered",
        request={"document_id": str(document_id), "action": "withdraw"},
        response={"document_id": str(document.id), "state": document.lifecycle_status},
    )
    record_audit_event(
        db,
        auth,
        action="document.withdrawn",
        resource_type="document",
        resource_id=str(document.id),
        details={"state": document.lifecycle_status},
    )
    await db.commit()
    return envelope(
        request_id,
        "answered",
        {"document_id": document.id, "state": document.lifecycle_status},
    )


async def _lifecycle_document(
    db: AsyncSession, auth: AuthContext, document_id: uuid.UUID
) -> Document:
    document = await db.get(Document, document_id)
    if document is None or document.workspace_id != auth.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "document not found")
    return document


async def _finish_document_lifecycle(
    *,
    db: AsyncSession,
    auth: AuthContext,
    request_id: str,
    document: Document,
    action: str,
    details: dict | None = None,
):
    payload = {
        "document_id": str(document.id),
        "state": document.lifecycle_status,
        **(details or {}),
    }
    record_interaction(
        db,
        auth,
        request_id=request_id,
        capability="sources.ingest",
        status="answered",
        request={"document_id": str(document.id), "action": action},
        response=payload,
    )
    record_audit_event(
        db,
        auth,
        action=f"document.{action}",
        resource_type="document",
        resource_id=str(document.id),
        details=payload,
    )
    await db.commit()
    return envelope(request_id, "answered", payload)


@router.post("/v1/documents/{document_id}/approve")
async def approve_document(
    document_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require("sources.review")),
    settings: Settings = Depends(get_settings),
):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    document = await _lifecycle_document(db, auth, document_id)
    try:
        await IngestionService(db, get_gateway(settings)).approve(document)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _finish_document_lifecycle(
        db=db, auth=auth, request_id=request_id, document=document, action="approved"
    )


@router.post("/v1/documents/{document_id}/publish")
async def publish_document(
    document_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require("sources.review")),
    settings: Settings = Depends(get_settings),
):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    document = await _lifecycle_document(db, auth, document_id)
    try:
        await IngestionService(db, get_gateway(settings)).publish(document)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _finish_document_lifecycle(
        db=db, auth=auth, request_id=request_id, document=document, action="published"
    )


@router.post("/v1/documents/{document_id}/reindex")
async def reindex_document(
    document_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require("sources.ingest")),
    settings: Settings = Depends(get_settings),
):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    document = await _lifecycle_document(db, auth, document_id)
    try:
        chunk_count = await IngestionService(db, get_gateway(settings)).reindex(document)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _finish_document_lifecycle(
        db=db,
        auth=auth,
        request_id=request_id,
        document=document,
        action="reindexed",
        details={"chunk_count": chunk_count},
    )


@router.get("/v1/catalog/events")
async def list_events(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require("sourcing")),
):
    events = list(
        (
            await db.scalars(
                select(SourcingEvent).where(SourcingEvent.workspace_id == auth.workspace_id)
            )
        ).all()
    )
    return {
        "items": [
            {
                "id": e.id,
                "title": e.title,
                "category": e.category,
                "participant_count": e.participant_count,
            }
            for e in events
        ]
    }


@router.get("/v1/catalog/products")
async def list_products(
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require("products.search")),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    stmt = select(Product).where(Product.workspace_id == auth.workspace_id)
    if Role.ADMIN not in auth.roles and Role.REVIEWER not in auth.roles:
        stmt = stmt.where(Product.visibility == Visibility.PUBLIC_WORKSPACE.value)
    stmt = stmt.order_by(Product.completeness.desc(), Product.title, Product.id)
    products = list((await db.scalars(stmt.offset(offset).limit(limit))).all())
    items = [
        {
            "id": p.id,
            "sku": p.sku,
            "title": p.title,
            "category": p.category,
            "list_price": str(p.list_price),
        }
        for p in products
        if can_read_product(auth, visibility=p.visibility)
    ]
    return {"items": items, "limit": limit, "offset": offset}


@router.post("/v1/audit-exports")
async def audit_exports(
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext = Depends(require("audit.export")),
):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    audit_events = list(
        (
            await db.scalars(
                select(AuditEvent)
                .where(AuditEvent.workspace_id == auth.workspace_id)
                .order_by(AuditEvent.created_at.desc())
                .limit(1000)
            )
        ).all()
    )
    interactions = list(
        (
            await db.scalars(
                select(Interaction)
                .where(Interaction.workspace_id == auth.workspace_id)
                .order_by(Interaction.created_at.desc())
                .limit(1000)
            )
        ).all()
    )
    payload = {
        "exported_at": datetime.now(UTC).isoformat(),
        "truncated": len(audit_events) == 1000 or len(interactions) == 1000,
        "audit_events": [
            {
                "id": event.id,
                "created_at": event.created_at,
                "principal_id": event.principal_id,
                "action": event.action,
                "resource_type": event.resource_type,
                "resource_id": event.resource_id,
                "details": event.details,
                "authorized": event.authorized,
            }
            for event in audit_events
        ],
        "interactions": [
            {
                "id": interaction.id,
                "created_at": interaction.created_at,
                "principal_id": interaction.principal_id,
                "request_id": interaction.request_id,
                "capability": interaction.capability,
                "status": interaction.status,
                "request": interaction.request,
                "response": interaction.response,
                "evidence": interaction.evidence,
                "execution_manifest": interaction.execution_manifest,
                "final_state": interaction.final_state,
            }
            for interaction in interactions
        ],
    }
    record_interaction(
        db,
        auth,
        request_id=request_id,
        capability="audit.export",
        status="accepted",
        request={},
        response={"exported_at": payload["exported_at"], "truncated": payload["truncated"]},
    )
    await db.commit()
    return envelope(request_id, "accepted", _jsonable(payload))
