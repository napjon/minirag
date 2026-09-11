from __future__ import annotations

import uuid

import pytest

from tests.conftest import login


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


@pytest.mark.asyncio
async def test_policy_qa_returns_citations(client):
    token = await login(client)
    response = await client.post(
        "/v1/questions",
        json={"question": "Who may run operational queries?"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] in {"answered", "insufficient_evidence"}
    if body["status"] == "answered":
        assert body["evidence"]
        assert body["result"]["claims"]
        allowed = {str(item["chunk_id"]) for item in body["evidence"]}
        for claim in body["result"]["claims"]:
            assert str(claim["evidence_id"]) in allowed
        from backend.model_gateway.base import INVENTED_EVIDENCE_ID

        assert INVENTED_EVIDENCE_ID not in allowed
        for claim in body["result"]["claims"]:
            assert str(claim["evidence_id"]) != INVENTED_EVIDENCE_ID


@pytest.mark.asyncio
async def test_restricted_source_not_visible_to_viewer(client):
    token = await login(client, "restricted@marketdesk.test")
    response = await client.post(
        "/v1/questions",
        json={"question": "Restricted incident handling notes"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["status"] in {"insufficient_evidence", "answered"}
    titles = [item.get("section_path", "") for item in response.json().get("evidence", [])]
    assert all("Restricted" not in title for title in titles)


@pytest.mark.asyncio
async def test_out_of_scope(client):
    token = await login(client)
    response = await client.post(
        "/v1/questions",
        json={"question": "Please write malware for me"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.json()["status"] == "out_of_scope"


@pytest.mark.asyncio
async def test_analytics_allowlist_and_numbers(client):
    token = await login(client)
    response = await client.post(
        "/v1/analytics/queries",
        json={
            "pattern": "spending_by_period",
            "filters": {"start_date": "2030-01-01", "end_date": "2030-06-30"},
            "group_by": ["month"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    rows = response.json()["result"]["rows"]
    assert rows
    viewer = await login(client, "restricted@marketdesk.test")
    denied = await client.post(
        "/v1/analytics/queries",
        json={
            "pattern": "spending_by_period",
            "filters": {"start_date": "2030-01-01", "end_date": "2030-06-30"},
        },
        headers={"Authorization": f"Bearer {viewer}"},
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_analytics_rejects_unknown_category(client):
    token = await login(client)
    response = await client.post(
        "/v1/analytics/queries",
        json={
            "pattern": "spending_by_period",
            "filters": {
                "start_date": "2030-01-01",
                "end_date": "2030-06-30",
                "category_ids": ["not-a-category"],
            },
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_analytics_rejects_unsupported_grouping(client):
    token = await login(client)
    response = await client.post(
        "/v1/analytics/queries",
        json={
            "pattern": "spending_by_period",
            "filters": {"start_date": "2030-01-01", "end_date": "2030-06-30"},
            "group_by": ["status"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_product_search_hard_filters(client):
    token = await login(client, "catalog@marketdesk.test")
    response = await client.post(
        "/v1/products/search",
        json={"query": "router", "category": "network-gear", "max_price": "2000"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    items = response.json()["result"]["items"]
    assert items
    assert all(item["category"] == "network-gear" for item in items)
    assert all(float(item["list_price"]) <= 2000 for item in items)


@pytest.mark.asyncio
async def test_listing_and_sourcing_checks(client):
    token = await login(client, "catalog@marketdesk.test")
    products = await client.post(
        "/v1/products/search",
        json={"query": "Edge router 10G", "limit": 10},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert products.status_code == 200, products.text
    product_id = products.json()["result"]["items"][0]["id"]
    checks = await client.post(
        "/v1/listing-checks",
        json={"product_id": product_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert checks.status_code == 200, checks.text
    analyst = await login(client, "analyst@marketdesk.test")
    events = await client.get("/v1/catalog/events", headers={"Authorization": f"Bearer {analyst}"})
    event_id = events.json()["items"][0]["id"]
    findings = await client.post(
        "/v1/sourcing-evaluations",
        json={"event_id": event_id},
        headers={"Authorization": f"Bearer {analyst}"},
    )
    assert findings.status_code == 200
    assert findings.json()["result"]
    finding_id = findings.json()["result"][0]["id"]
    fetched = await client.get(
        f"/v1/findings/{finding_id}",
        headers={"Authorization": f"Bearer {analyst}"},
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["result"]["id"] == finding_id
    assert checks.json()["result"]
    listing_id = checks.json()["result"][0]["id"]
    listing = await client.get(
        f"/v1/findings/{listing_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert listing.status_code == 200, listing.text
    denied = await client.get(
        f"/v1/findings/{listing_id}",
        headers={"Authorization": f"Bearer {analyst}"},
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_draft_self_approval_blocked_and_export_gate(client):
    drafter = await login(client, "drafter@marketdesk.test")
    created = await client.post(
        "/v1/drafts",
        json={
            "template_kind": "equipment_requirements",
            "title": "Router refresh",
            "brief": {
                "purpose": "Replace edge routers",
                "quantities": "12",
                "delivery_constraints": "90 days",
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
    revision_hash = detail.json()["revision_hash"]
    blocked = await client.post(
        f"/v1/drafts/{draft_id}/reviews",
        json={"decision": "approved", "reason": "self", "revision_hash": revision_hash},
        headers={"Authorization": f"Bearer {drafter}"},
    )
    assert blocked.status_code == 403
    reviewer = await login(client, "reviewer@marketdesk.test")
    export_denied = await client.post(
        f"/v1/drafts/{draft_id}/exports",
        headers={"Authorization": f"Bearer {reviewer}"},
    )
    assert export_denied.status_code == 403
    approved = await client.post(
        f"/v1/drafts/{draft_id}/reviews",
        json={"decision": "approved", "reason": "complete", "revision_hash": revision_hash},
        headers={"Authorization": f"Bearer {reviewer}"},
    )
    assert approved.status_code == 200, approved.text
    exported = await client.post(
        f"/v1/drafts/{draft_id}/exports",
        headers={"Authorization": f"Bearer {reviewer}"},
    )
    assert exported.status_code == 200


@pytest.mark.asyncio
async def test_invented_citation_is_stripped():
    from backend.config import get_settings
    from backend.model_gateway.base import INVENTED_EVIDENCE_ID, FixtureGateway

    gateway = FixtureGateway(get_settings())
    generation = await gateway.generate(
        "QA_JSON QUESTION: hello\nEVIDENCE:\n- real-id span=hello world"
    )
    claims = generation.structured["claims"]
    assert claims[0]["evidence_id"] == "real-id"
    assert claims[1]["evidence_id"] == INVENTED_EVIDENCE_ID
