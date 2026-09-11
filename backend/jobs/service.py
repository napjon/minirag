from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.security import AuthContext
from backend.domain.enums import JobState, Role
from backend.domain.models import AuditEvent, Job


class IdempotencyConflict(ValueError):
    """Raised when a key is replayed after the caller's permissions changed."""


class JobService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_or_get(
        self,
        auth: AuthContext,
        *,
        job_type: str,
        idempotency_key: str,
        progress: dict[str, Any] | None = None,
    ) -> Job:
        existing = await self.db.scalar(
            select(Job).where(
                Job.workspace_id == auth.workspace_id,
                Job.principal_id == auth.principal_id,
                Job.job_type == job_type,
                Job.idempotency_key == idempotency_key,
            )
        )
        if existing:
            requested_payload = (progress or {}).get("payload")
            existing_payload = (existing.progress or {}).get("payload")
            if (
                requested_payload is not None
                and existing_payload is not None
                and requested_payload != existing_payload
            ):
                raise IdempotencyConflict("idempotency key was already used for another request")
            if existing.permission_fingerprint != auth.permission_fingerprint:
                raise IdempotencyConflict(
                    "idempotency key cannot be reused after permission change"
                )
            return existing
        job = Job(
            workspace_id=auth.workspace_id,
            principal_id=auth.principal_id,
            job_type=job_type,
            state=JobState.QUEUED.value,
            idempotency_key=idempotency_key,
            progress=progress or {"stage": "queued"},
            permission_fingerprint=auth.permission_fingerprint,
        )
        try:
            async with self.db.begin_nested():
                self.db.add(job)
                await self.db.flush()
        except IntegrityError as exc:
            existing = await self.db.scalar(
                select(Job).where(
                    Job.workspace_id == auth.workspace_id,
                    Job.principal_id == auth.principal_id,
                    Job.job_type == job_type,
                    Job.idempotency_key == idempotency_key,
                )
            )
            if existing is None:
                raise exc from None
            requested_payload = (progress or {}).get("payload")
            existing_payload = (existing.progress or {}).get("payload")
            if (
                requested_payload is not None
                and existing_payload is not None
                and requested_payload != existing_payload
            ):
                raise IdempotencyConflict(
                    "idempotency key was already used for another request"
                ) from exc
            if existing.permission_fingerprint != auth.permission_fingerprint:
                raise IdempotencyConflict(
                    "idempotency key cannot be reused after permission change"
                ) from exc
            return existing
        return job

    async def run(self, job: Job, fn) -> Job:
        # Serialize replayed requests for the same durable job. The lock is
        # held through the terminal transition, so a refresh cannot execute a
        # second copy while the first request is still running.
        locked = await self.db.scalar(select(Job).where(Job.id == job.id).with_for_update())
        if locked is None:
            return job
        job = locked
        if job.state == JobState.SUCCEEDED.value and job.result is not None:
            return job
        if (
            job.state == JobState.RUNNING.value
            and job.lease_until is not None
            and job.lease_until > datetime.now(UTC)
        ):
            return job
        job.state = JobState.RUNNING.value
        job.attempts += 1
        job.lease_until = datetime.now(UTC) + timedelta(minutes=5)
        await self.db.flush()
        try:
            result = await fn(job)
            job.result = result
            job.state = JobState.SUCCEEDED.value
            job.progress = {**(job.progress or {}), "stage": "done"}
            terminal_action = "job.succeeded"
        except Exception as exc:  # noqa: BLE001
            job.state = JobState.FAILED.value
            job.error = str(exc)
            job.progress = {**(job.progress or {}), "stage": "failed"}
            terminal_action = "job.failed"
        self.db.add(
            AuditEvent(
                workspace_id=job.workspace_id,
                principal_id=job.principal_id,
                action=terminal_action,
                resource_type="job",
                resource_id=str(job.id),
                details={"job_type": job.job_type, "attempts": job.attempts},
                authorized=True,
            )
        )
        await self.db.flush()
        return job

    async def get(self, job_id: uuid.UUID, auth: AuthContext | None = None) -> Job | None:
        job = await self.db.get(Job, job_id)
        if job is None:
            return None
        if auth is None:
            return job
        if job.workspace_id != auth.workspace_id:
            return None
        if job.principal_id != auth.principal_id and Role.ADMIN not in auth.roles:
            return None
        return job
