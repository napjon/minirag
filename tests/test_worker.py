from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from backend.config import get_settings
from backend.db import apply_rls, get_sessionmaker
from backend.domain.models import Job, Principal, Workspace
from backend.jobs.worker import process_next
from tests.conftest import login


async def _queue_draft(client, monkeypatch) -> tuple[str, str]:
    settings = get_settings()
    monkeypatch.setattr(settings, "job_execution_mode", "worker")
    token = await login(client, "drafter@marketdesk.test")
    created = await client.post(
        "/v1/drafts",
        json={
            "template_kind": "equipment_requirements",
            "title": f"Queued synthetic draft {uuid.uuid4().hex[:8]}",
            "brief": {
                "purpose": "Document a synthetic equipment need",
                "quantities": "Two units",
                "delivery_constraints": "Test location",
                "acceptance": "Reviewed evidence",
            },
            "idempotency_key": str(uuid.uuid4()),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert created.status_code == 202, created.text
    assert created.json()["status"] == "accepted"
    assert created.json()["result"]["result"] is None
    return str(created.json()["result"]["job_id"]), token


@pytest.mark.asyncio
async def test_worker_claims_executes_and_does_not_replay_completed_job(client, monkeypatch):
    job_id, token = await _queue_draft(client, monkeypatch)
    settings = get_settings()
    completed = await process_next(settings, job_id=uuid.UUID(job_id))
    assert completed is not None
    assert completed.state == "succeeded"
    assert completed.result and completed.result["draft_id"]

    replay = await process_next(settings, job_id=uuid.UUID(job_id))
    assert replay is None
    shown = await client.get(f"/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {token}"})
    assert shown.status_code == 200, shown.text
    assert shown.json()["state"] == "succeeded"


@pytest.mark.asyncio
async def test_worker_rejects_job_when_permission_fingerprint_changed(client, monkeypatch):
    job_id, token = await _queue_draft(client, monkeypatch)
    async with get_sessionmaker()() as db:
        workspace = await db.scalar(select(Workspace).where(Workspace.slug == "harbor"))
        principal = await db.scalar(
            select(Principal).where(Principal.email == "drafter@marketdesk.test")
        )
        assert workspace is not None and principal is not None
        await apply_rls(db, str(workspace.id), str(principal.id))
        job = await db.get(Job, uuid.UUID(job_id))
        assert job is not None
        job.permission_fingerprint = "stale-permissions"
        await db.commit()

    rejected = await process_next(get_settings(), job_id=uuid.UUID(job_id))
    assert rejected is not None
    assert rejected.state == "rejected"
    assert rejected.error == "permissions changed before execution"
    shown = await client.get(f"/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {token}"})
    assert shown.status_code == 200, shown.text
    assert shown.json()["state"] == "rejected"


@pytest.mark.asyncio
async def test_queued_idempotency_key_cannot_be_reused_for_another_payload(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "job_execution_mode", "worker")
    token = await login(client, "drafter@marketdesk.test")
    key = str(uuid.uuid4())
    base = {
        "template_kind": "equipment_requirements",
        "title": "First synthetic payload",
        "brief": {
            "purpose": "First purpose",
            "quantities": "One",
            "delivery_constraints": "Test",
            "acceptance": "Review",
        },
        "idempotency_key": key,
    }
    first = await client.post("/v1/drafts", json=base, headers={"Authorization": f"Bearer {token}"})
    assert first.status_code == 202, first.text
    changed = {**base, "title": "Changed synthetic payload"}
    conflict = await client.post(
        "/v1/drafts", json=changed, headers={"Authorization": f"Bearer {token}"}
    )
    assert conflict.status_code == 409


@pytest.mark.asyncio
async def test_worker_persists_failure_and_stops_after_retry_limit(client, monkeypatch):
    job_id, _ = await _queue_draft(client, monkeypatch)
    async with get_sessionmaker()() as db:
        workspace = await db.scalar(select(Workspace).where(Workspace.slug == "harbor"))
        principal = await db.scalar(
            select(Principal).where(Principal.email == "drafter@marketdesk.test")
        )
        assert workspace is not None and principal is not None
        await apply_rls(db, str(workspace.id), str(principal.id))
        job = await db.get(Job, uuid.UUID(job_id))
        assert job is not None
        job.progress = {
            **job.progress,
            "payload": {**job.progress["payload"], "template_kind": "unsupported-template"},
        }
        await db.commit()

    settings = get_settings()
    for attempt in range(1, settings.job_max_attempts + 1):
        failed = await process_next(settings, job_id=uuid.UUID(job_id))
        assert failed is not None
        assert failed.state == "failed"
        assert failed.attempts == attempt
        assert failed.error
    assert await process_next(settings, job_id=uuid.UUID(job_id)) is None
