from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from backend.db import apply_rls, get_sessionmaker
from backend.domain.enums import Visibility
from backend.domain.models import Document, Principal, Workspace
from tests.conftest import login

RESTRICTED_BODY = "visible only to the incident-response group"
ANALYTICS_BODY = {
    "pattern": "spending_by_period",
    "filters": {"start_date": "2030-01-01", "end_date": "2030-06-30"},
    "group_by": ["month"],
}


async def _document_id(
    *, email: str, visibility: str | None = None, title_contains: str | None = None
) -> str:
    async with get_sessionmaker()() as db:
        workspace = await db.scalar(select(Workspace).where(Workspace.slug == "harbor"))
        principal = await db.scalar(select(Principal).where(Principal.email == email))
        assert workspace is not None and principal is not None
        await apply_rls(db, str(workspace.id), str(principal.id))
        stmt = select(Document).where(Document.workspace_id == workspace.id)
        if visibility is not None:
            stmt = stmt.where(Document.visibility == visibility)
        documents = list((await db.scalars(stmt)).all())
        if title_contains:
            documents = [row for row in documents if title_contains.lower() in row.title.lower()]
        assert documents
        return str(documents[0].id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "email,path,method",
    [
        ("restricted@marketdesk.test", "/v1/analytics/queries", "POST"),
        ("restricted@marketdesk.test", "/v1/listing-checks", "POST"),
        ("restricted@marketdesk.test", "/v1/audit-exports", "POST"),
        ("drafter@marketdesk.test", "/v1/analytics/queries", "POST"),
        ("drafter@marketdesk.test", "/v1/listing-checks", "POST"),
        ("drafter@marketdesk.test", "/v1/audit-exports", "POST"),
        ("analyst@marketdesk.test", "/v1/listing-checks", "POST"),
        ("analyst@marketdesk.test", "/v1/audit-exports", "POST"),
    ],
)
async def test_viewer_roles_cannot_hit_privileged_capabilities(client, email, path, method):
    token = await login(client, email)
    headers = {"Authorization": f"Bearer {token}"}
    if path == "/v1/analytics/queries":
        response = await client.request(method, path, json=ANALYTICS_BODY, headers=headers)
    elif path == "/v1/listing-checks":
        catalog = await login(client, "catalog@marketdesk.test")
        products = await client.get(
            "/v1/catalog/products",
            headers={"Authorization": f"Bearer {catalog}"},
        )
        assert products.status_code == 200, products.text
        product_id = products.json()["items"][0]["id"]
        response = await client.request(
            method, path, json={"product_id": product_id}, headers=headers
        )
    else:
        response = await client.request(method, path, headers=headers)
    assert response.status_code == 403
    assert RESTRICTED_BODY not in response.text.lower()


@pytest.mark.asyncio
async def test_drafter_cannot_review_own_draft(client):
    drafter = await login(client, "drafter@marketdesk.test")
    created = await client.post(
        "/v1/drafts",
        json={
            "template_kind": "equipment_requirements",
            "title": "Authorization self-review",
            "brief": {
                "purpose": "Replace edge routers",
                "quantities": "4",
                "delivery_constraints": "60 days",
                "acceptance": "burn-in test",
            },
            "idempotency_key": str(uuid.uuid4()),
        },
        headers={"Authorization": f"Bearer {drafter}"},
    )
    assert created.status_code == 202, created.text
    draft_id = created.json()["result"]["result"]["draft_id"]
    detail = await client.get(
        f"/v1/drafts/{draft_id}", headers={"Authorization": f"Bearer {drafter}"}
    )
    blocked = await client.post(
        f"/v1/drafts/{draft_id}/reviews",
        json={
            "decision": "approved",
            "reason": "self",
            "revision_hash": detail.json()["revision_hash"],
        },
        headers={"Authorization": f"Bearer {drafter}"},
    )
    assert blocked.status_code == 403


@pytest.mark.asyncio
async def test_author_admin_cannot_approve_own_draft(client):
    admin = await login(client, "admin@marketdesk.test")
    created = await client.post(
        "/v1/drafts",
        json={
            "template_kind": "equipment_requirements",
            "title": "Admin authored draft",
            "brief": {
                "purpose": "Replace rectifiers",
                "quantities": "2",
                "delivery_constraints": "30 days",
                "acceptance": "site test",
            },
            "idempotency_key": str(uuid.uuid4()),
        },
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert created.status_code == 202, created.text
    draft_id = created.json()["result"]["result"]["draft_id"]
    detail = await client.get(
        f"/v1/drafts/{draft_id}", headers={"Authorization": f"Bearer {admin}"}
    )
    blocked = await client.post(
        f"/v1/drafts/{draft_id}/reviews",
        json={
            "decision": "approved",
            "reason": "self",
            "revision_hash": detail.json()["revision_hash"],
        },
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert blocked.status_code == 403
    assert "cannot approve their own drafts" in blocked.text


@pytest.mark.asyncio
async def test_restricted_viewer_does_not_receive_restricted_source_text(client):
    source_id = await _document_id(
        email="admin@marketdesk.test",
        visibility=Visibility.RESTRICTED.value,
        title_contains="Restricted incident",
    )
    token = await login(client, "restricted@marketdesk.test")
    response = await client.get(
        f"/v1/documents/{source_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    payload = response.text.lower()
    assert RESTRICTED_BODY not in payload
    if response.status_code == 200:
        assert RESTRICTED_BODY not in (response.json().get("text") or "").lower()
    else:
        assert response.status_code in {401, 403, 404}


@pytest.mark.asyncio
async def test_analyst_without_group_does_not_receive_restricted_source_text(client):
    source_id = await _document_id(
        email="admin@marketdesk.test",
        visibility=Visibility.RESTRICTED.value,
        title_contains="Restricted incident",
    )
    token = await login(client, "analyst@marketdesk.test")
    response = await client.get(
        f"/v1/documents/{source_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert RESTRICTED_BODY not in response.text.lower()
    if response.status_code == 200:
        assert RESTRICTED_BODY not in (response.json().get("text") or "").lower()
    else:
        assert response.status_code in {401, 403, 404}


@pytest.mark.asyncio
async def test_reviewer_can_read_restricted_source(client):
    source_id = await _document_id(
        email="admin@marketdesk.test",
        visibility=Visibility.RESTRICTED.value,
        title_contains="Restricted incident",
    )
    token = await login(client, "reviewer@marketdesk.test")
    response = await client.get(
        f"/v1/documents/{source_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert RESTRICTED_BODY in (response.json().get("text") or "").lower()


@pytest.mark.asyncio
async def test_restricted_viewer_can_read_public_source(client):
    source_id = await _document_id(
        email="admin@marketdesk.test",
        visibility=Visibility.PUBLIC_WORKSPACE.value,
        title_contains="Account and role access",
    )
    token = await login(client, "restricted@marketdesk.test")
    response = await client.get(
        f"/v1/documents/{source_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    text = response.json().get("text") or ""
    assert "analysts may run operational queries" in text.lower()
    assert RESTRICTED_BODY not in text.lower()


@pytest.mark.asyncio
async def test_source_lookup_outside_workspace_is_not_found(client):
    token = await login(client, "restricted@marketdesk.test")
    response = await client.get(
        f"/v1/documents/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404
    assert RESTRICTED_BODY not in response.text.lower()
