from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import func, select

from backend.config import get_settings
from backend.db import apply_rls, get_sessionmaker
from backend.domain.models import Document, Principal, Source, Workspace
from backend.ingestion.service import IngestionService
from backend.model_gateway.base import get_gateway
from tests.conftest import login


async def _harbor_source_id() -> uuid.UUID:
    async with get_sessionmaker()() as db:
        workspace = await db.scalar(select(Workspace).where(Workspace.slug == "harbor"))
        principal = await db.scalar(
            select(Principal).where(Principal.email == "admin@marketdesk.test")
        )
        assert workspace is not None and principal is not None
        await apply_rls(db, str(workspace.id), str(principal.id))
        source = await db.scalar(select(Source).where(Source.workspace_id == workspace.id))
        assert source is not None
        return source.id


async def _document_count(title: str) -> int:
    async with get_sessionmaker()() as db:
        workspace = await db.scalar(select(Workspace).where(Workspace.slug == "harbor"))
        principal = await db.scalar(
            select(Principal).where(Principal.email == "admin@marketdesk.test")
        )
        await apply_rls(db, str(workspace.id), str(principal.id))
        return await db.scalar(
            select(func.count()).select_from(Document).where(Document.title == title)
        )


@pytest.mark.asyncio
async def test_upload_txt_is_searchable(client):
    admin = await login(client, "admin@marketdesk.test")
    source_id = await _harbor_source_id()
    token = f"cobalt-upload-token-{uuid.uuid4().hex[:8]}"
    title = f"Cobalt upload policy {uuid.uuid4().hex[:8]}"
    body = f"# {title}\nAnalysts may inspect {token} records after approval.\n"
    uploaded = await client.post(
        "/v1/documents/uploads",
        data={
            "source_id": str(source_id),
            "title": title,
            "topic": "account-access",
            "language": "en",
            "idempotency_key": str(uuid.uuid4()),
        },
        files={"file": ("cobalt.txt", body.encode(), "text/plain")},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert uploaded.status_code == 202, uploaded.text
    payload = uploaded.json()["result"]
    document_id = payload["result"]["document_id"]
    analyst = await login(client, "analyst@marketdesk.test")
    shown = await client.get(
        f"/v1/documents/{document_id}",
        headers={"Authorization": f"Bearer {analyst}"},
    )
    assert shown.status_code == 200, shown.text
    assert token in shown.json()["text"]
    asked = await client.post(
        "/v1/questions",
        json={"question": token},
        headers={"Authorization": f"Bearer {analyst}"},
    )
    assert asked.status_code == 200, asked.text
    evidence = asked.json().get("evidence") or []
    blob = " ".join(
        f"{item.get('section_path') or ''} {item.get('supporting_span') or ''}" for item in evidence
    )
    assert token in blob or title in blob


@pytest.mark.asyncio
async def test_withdraw_hides_uploaded_document(client):
    admin = await login(client, "admin@marketdesk.test")
    source_id = await _harbor_source_id()
    token = f"cobalt-withdraw-token-{uuid.uuid4().hex[:8]}"
    title = f"Temporary cobalt withdraw policy {uuid.uuid4().hex[:8]}"
    body = f"# {title}\nThis {token} policy will be withdrawn from search.\n"
    uploaded = await client.post(
        "/v1/documents/uploads",
        data={
            "source_id": str(source_id),
            "title": title,
            "topic": "ordering",
            "language": "en",
            "idempotency_key": str(uuid.uuid4()),
        },
        files={"file": ("withdraw.txt", body.encode(), "text/plain")},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert uploaded.status_code == 202, uploaded.text
    document_id = uploaded.json()["result"]["result"]["document_id"]
    withdrawn = await client.post(
        f"/v1/documents/{document_id}/withdraw",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert withdrawn.status_code == 200, withdrawn.text
    analyst = await login(client, "analyst@marketdesk.test")
    hidden = await client.get(
        f"/v1/documents/{document_id}",
        headers={"Authorization": f"Bearer {analyst}"},
    )
    assert hidden.status_code in {403, 404}
    asked = await client.post(
        "/v1/questions",
        json={"question": title},
        headers={"Authorization": f"Bearer {analyst}"},
    )
    assert asked.status_code == 200, asked.text
    evidence = asked.json().get("evidence") or []
    assert all(title not in (item.get("section_path") or "") for item in evidence)


@pytest.mark.asyncio
async def test_ingest_idempotency_replays_same_document(client):
    admin = await login(client, "admin@marketdesk.test")
    source_id = await _harbor_source_id()
    key = str(uuid.uuid4())
    title = f"Idempotent cobalt upload {uuid.uuid4().hex[:8]}"
    body = f"# {title}\nReplay must not create a second {title} document.\n"
    data = {
        "source_id": str(source_id),
        "title": title,
        "topic": "account-access",
        "language": "en",
        "idempotency_key": key,
    }
    first = await client.post(
        "/v1/documents/uploads",
        data=data,
        files={"file": ("idempotent.txt", body.encode(), "text/plain")},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert first.status_code == 202, first.text
    document_a = first.json()["result"]["result"]["document_id"]
    second = await client.post(
        "/v1/documents/uploads",
        data=data,
        files={"file": ("idempotent.txt", body.encode(), "text/plain")},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert second.status_code == 202, second.text
    document_b = second.json()["result"]["result"]["document_id"]
    assert document_a == document_b
    assert await _document_count(title) == 1


@pytest.mark.asyncio
async def test_ingest_missing_source_persists_failed_job(client):
    admin = await login(client, "admin@marketdesk.test")
    uploaded = await client.post(
        "/v1/documents/uploads",
        data={
            "source_id": str(uuid.uuid4()),
            "title": "Missing source ingest",
            "topic": "account-access",
            "language": "en",
            "idempotency_key": str(uuid.uuid4()),
        },
        files={"file": ("missing.txt", b"should fail inside the job", "text/plain")},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert uploaded.status_code == 202, uploaded.text
    job_id = uploaded.json()["result"]["job_id"]
    assert uploaded.json()["result"].get("error")
    owned = await client.get(f"/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {admin}"})
    assert owned.status_code == 200, owned.text
    body = owned.json()
    assert body["state"] == "failed"
    assert body["error"]


@pytest.mark.asyncio
async def test_ingest_job_hidden_from_other_member(client):
    admin = await login(client, "admin@marketdesk.test")
    source_id = await _harbor_source_id()
    uploaded = await client.post(
        "/v1/documents/uploads",
        data={
            "source_id": str(source_id),
            "title": f"Private ingest job {uuid.uuid4().hex[:8]}",
            "topic": "account-access",
            "language": "en",
            "idempotency_key": str(uuid.uuid4()),
        },
        files={"file": ("private.txt", b"owner-scoped ingest job payload", "text/plain")},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert uploaded.status_code == 202, uploaded.text
    job_id = uploaded.json()["result"]["job_id"]
    analyst = await login(client, "analyst@marketdesk.test")
    hidden = await client.get(f"/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {analyst}"})
    assert hidden.status_code == 404
    own = await client.get(f"/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {admin}"})
    assert own.status_code == 200


@pytest.mark.asyncio
async def test_historical_question_uses_effective_revision(client):
    admin = await login(client, "admin@marketdesk.test")
    source_id = await _harbor_source_id()
    old_token = f"historical-old-{uuid.uuid4().hex[:8]}"
    new_token = f"historical-new-{uuid.uuid4().hex[:8]}"
    uploaded = await client.post(
        "/v1/documents/uploads",
        data={
            "source_id": str(source_id),
            "title": f"Versioned policy {uuid.uuid4().hex[:8]}",
            "topic": "account-access",
            "language": "en",
            "idempotency_key": str(uuid.uuid4()),
        },
        files={"file": ("versioned.txt", f"Old rule {old_token}".encode(), "text/plain")},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert uploaded.status_code == 202, uploaded.text
    document_id = uuid.UUID(uploaded.json()["result"]["result"]["document_id"])

    async with get_sessionmaker()() as db:
        workspace = await db.scalar(select(Workspace).where(Workspace.slug == "harbor"))
        principal = await db.scalar(
            select(Principal).where(Principal.email == "admin@marketdesk.test")
        )
        assert workspace is not None and principal is not None
        await apply_rls(db, str(workspace.id), str(principal.id))
        document = await db.get(Document, document_id)
        assert document is not None
        await IngestionService(db, get_gateway(get_settings())).supersede(
            document,
            body=f"New rule {new_token}",
            language="en",
            effective_from=date(2031, 1, 1),
            publish=True,
        )
        await db.commit()

    analyst = await login(client, "analyst@marketdesk.test")
    old = await client.post(
        "/v1/questions",
        json={"question": old_token, "as_of": "2030-06-01"},
        headers={"Authorization": f"Bearer {analyst}"},
    )
    assert old.status_code == 200, old.text
    old_blob = " ".join(item.get("supporting_span", "") for item in old.json().get("evidence", []))
    assert old_token in old_blob
    assert new_token not in old_blob

    new = await client.post(
        "/v1/questions",
        json={"question": new_token, "as_of": "2031-06-01"},
        headers={"Authorization": f"Bearer {analyst}"},
    )
    assert new.status_code == 200, new.text
    new_blob = " ".join(item.get("supporting_span", "") for item in new.json().get("evidence", []))
    assert new_token in new_blob


@pytest.mark.asyncio
async def test_document_requires_review_before_publish_and_can_be_reindexed(client):
    admin = await login(client, "admin@marketdesk.test")
    reviewer = await login(client, "reviewer@marketdesk.test")
    analyst = await login(client, "analyst@marketdesk.test")
    source_id = await _harbor_source_id()
    title = f"Reviewed lifecycle {uuid.uuid4().hex[:8]}"
    uploaded = await client.post(
        "/v1/documents/uploads",
        data={
            "source_id": str(source_id),
            "title": title,
            "topic": "account-access",
            "language": "en",
            "idempotency_key": str(uuid.uuid4()),
            "publish": "false",
        },
        files={"file": ("review.txt", b"Reviewed lifecycle evidence.", "text/plain")},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert uploaded.status_code == 202, uploaded.text
    result = uploaded.json()["result"]["result"]
    assert result["state"] == "awaiting_approval"
    document_id = result["document_id"]

    hidden = await client.get(
        f"/v1/documents/{document_id}", headers={"Authorization": f"Bearer {analyst}"}
    )
    assert hidden.status_code == 404
    premature = await client.post(
        f"/v1/documents/{document_id}/publish",
        headers={"Authorization": f"Bearer {reviewer}"},
    )
    assert premature.status_code == 409

    approved = await client.post(
        f"/v1/documents/{document_id}/approve",
        headers={"Authorization": f"Bearer {reviewer}"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["result"]["state"] == "approved"
    published = await client.post(
        f"/v1/documents/{document_id}/publish",
        headers={"Authorization": f"Bearer {reviewer}"},
    )
    assert published.status_code == 200, published.text
    assert published.json()["result"]["state"] == "published"
    visible = await client.get(
        f"/v1/documents/{document_id}", headers={"Authorization": f"Bearer {analyst}"}
    )
    assert visible.status_code == 200, visible.text

    reindexed = await client.post(
        f"/v1/documents/{document_id}/reindex",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert reindexed.status_code == 200, reindexed.text
    assert reindexed.json()["result"]["chunk_count"] >= 1


@pytest.mark.asyncio
async def test_admin_can_create_an_anonymized_source(client):
    admin = await login(client, "admin@marketdesk.test")
    created = await client.post(
        "/v1/sources",
        json={
            "name": f"Synthetic source {uuid.uuid4().hex[:8]}",
            "source_type": "policy",
            "authority_class": "current_policy",
            "owner_role": "admin",
        },
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert created.status_code == 201, created.text
    source_id = created.json()["result"]["source_id"]
    loaded = await client.get(
        f"/v1/sources/{source_id}", headers={"Authorization": f"Bearer {admin}"}
    )
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["source_type"] == "policy"
