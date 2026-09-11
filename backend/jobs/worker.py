from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.auth.security import AuthContext, _membership_groups, _membership_roles
from backend.config import Settings, get_settings
from backend.domain.enums import JobState, JobType
from backend.domain.models import AuditEvent, Job, Membership, Principal
from backend.drafting.service import DraftingService
from backend.model_gateway.base import get_gateway


async def claim_job(
    db: AsyncSession,
    *,
    settings: Settings,
    job_id: uuid.UUID | None = None,
) -> Job | None:
    now = datetime.now(UTC)
    stmt = (
        select(Job)
        .where(
            Job.attempts < settings.job_max_attempts,
            or_(
                Job.state.in_([JobState.QUEUED.value, JobState.FAILED.value]),
                (Job.state == JobState.RUNNING.value) & (Job.lease_until < now),
            ),
        )
        .order_by(Job.created_at, Job.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job_id is not None:
        stmt = stmt.where(Job.id == job_id)
    job = await db.scalar(stmt)
    if job is None:
        return None
    job.state = JobState.RUNNING.value
    job.attempts += 1
    job.lease_until = now + timedelta(seconds=settings.job_lease_seconds)
    job.progress = {**(job.progress or {}), "stage": "running"}
    await db.flush()
    return job


async def _auth_for_job(db: AsyncSession, job: Job) -> AuthContext | None:
    membership = await db.scalar(
        select(Membership).where(
            Membership.workspace_id == job.workspace_id,
            Membership.principal_id == job.principal_id,
        )
    )
    principal = await db.get(Principal, job.principal_id)
    if membership is None or principal is None or not principal.is_active:
        return None
    roles = _membership_roles(membership.roles)
    groups = _membership_groups(membership.group_ids)
    fingerprint = "|".join(sorted([*(role.value for role in roles), *groups]))
    return AuthContext(
        principal_id=principal.id,
        workspace_id=job.workspace_id,
        subject=principal.subject,
        email=principal.email,
        display_name=principal.display_name,
        roles=roles,
        group_ids=groups,
        permission_fingerprint=fingerprint,
    )


async def execute_claimed_job(db: AsyncSession, job: Job, settings: Settings) -> Job:
    auth = await _auth_for_job(db, job)
    if auth is None or auth.permission_fingerprint != job.permission_fingerprint:
        job.state = JobState.REJECTED.value
        job.error = "permissions changed before execution"
    elif job.job_type == JobType.DRAFT.value and auth.can("drafts.create"):
        payload = (job.progress or {}).get("payload") or {}
        try:
            draft = await DraftingService(db, get_gateway(settings)).create(
                auth,
                template_kind=str(payload["template_kind"]),
                title=str(payload["title"]),
                brief=dict(payload["brief"]),
            )
            job.result = {"draft_id": str(draft.id), "state": draft.state}
            job.state = JobState.SUCCEEDED.value
            job.error = None
        except Exception as exc:  # noqa: BLE001
            job.state = JobState.FAILED.value
            job.error = str(exc)
    else:
        job.state = JobState.REJECTED.value
        job.error = "unsupported job type or capability"
    job.lease_until = None
    job.progress = {**(job.progress or {}), "stage": job.state}
    db.add(
        AuditEvent(
            workspace_id=job.workspace_id,
            principal_id=job.principal_id,
            action=f"job.{job.state}",
            resource_type="job",
            resource_id=str(job.id),
            details={"job_type": job.job_type, "attempts": job.attempts},
            authorized=job.state != JobState.REJECTED.value,
        )
    )
    await db.flush()
    return job


async def process_next(
    settings: Settings | None = None, *, job_id: uuid.UUID | None = None
) -> Job | None:
    settings = settings or get_settings()
    engine = create_async_engine(settings.admin_database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        return await _process_next_with_sessions(sessions, settings=settings, job_id=job_id)
    finally:
        await engine.dispose()


async def _process_next_with_sessions(
    sessions: async_sessionmaker[AsyncSession],
    *,
    settings: Settings,
    job_id: uuid.UUID | None = None,
) -> Job | None:
    async with sessions() as db:
        async with db.begin():
            job = await claim_job(db, settings=settings, job_id=job_id)
        if job is None:
            return None
        async with db.begin():
            current = await db.get(Job, job.id)
            if current is None or current.state != JobState.RUNNING.value:
                return None
            await execute_claimed_job(db, current, settings)
        return current


async def run_forever(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    engine = create_async_engine(settings.admin_database_url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        while True:
            processed = await _process_next_with_sessions(sessions, settings=settings)
            if processed is None:
                await asyncio.sleep(settings.job_poll_seconds)
    finally:
        await engine.dispose()


def run() -> None:
    asyncio.run(run_forever())
