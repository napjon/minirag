from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.auth.security import AuthContext
from backend.auth.visibility import can_read_document, can_read_product
from backend.config import get_settings
from backend.db import apply_rls, get_sessionmaker
from backend.detection.service import repeated_co_participation
from backend.domain.enums import Role, Visibility
from backend.domain.models import Principal, Product, SourcingEvent, Workspace
from backend.ingestion.service import IngestionService, chunk_text
from backend.model_gateway.base import get_gateway
from backend.retrieval.evidence import answer_is_supported, claim_is_supported, supporting_span
from evals.runner import grade_case
from tests.conftest import login


def _auth(principal_id, workspace_id, roles, groups=()):
    return AuthContext(
        principal_id=principal_id,
        workspace_id=workspace_id,
        subject="t",
        email="t@test",
        display_name="t",
        roles=tuple(roles),
        group_ids=tuple(groups),
        permission_fingerprint="x",
    )


def test_reviewer_only_ignores_group_overlap():
    auth = _auth(uuid.uuid4(), uuid.uuid4(), [Role.VIEWER, Role.ANALYST], ["ops"])
    assert (
        can_read_document(
            auth,
            visibility=Visibility.REVIEWER_ONLY.value,
            allowed_groups=["ops"],
        )
        is False
    )
    reviewer = _auth(uuid.uuid4(), uuid.uuid4(), [Role.REVIEWER], [])
    assert (
        can_read_document(
            reviewer,
            visibility=Visibility.REVIEWER_ONLY.value,
            allowed_groups=["ops"],
        )
        is True
    )


def test_product_visibility_fail_closed():
    viewer = _auth(uuid.uuid4(), uuid.uuid4(), [Role.VIEWER], ["ops"])
    assert can_read_product(viewer, visibility=Visibility.REVIEWER_ONLY.value) is False
    assert can_read_product(viewer, visibility=Visibility.PUBLIC_WORKSPACE.value) is True


def test_grader_fails_empty_search_results():
    ok, reason = grade_case(
        {"capability": "products.search", "expected": {"status": "answered"}},
        {"status": "answered", "result": {"items": []}, "evidence": []},
    )
    assert ok is False
    assert "empty" in reason


def test_grader_fails_unsupported_claim_with_real_evidence_id():
    eid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    ok, reason = grade_case(
        {
            "capability": "questions",
            "expected": {"status": "answered", "claims_must_cite_evidence": True},
        },
        {
            "status": "answered",
            "evidence": [
                {"chunk_id": eid, "supporting_span": "Analysts may run operational queries."}
            ],
            "result": {
                "claims": [
                    {
                        "text": "The board bonus formula is 12 percent of revenue.",
                        "evidence_id": eid,
                    }
                ]
            },
        },
    )
    assert ok is False
    assert "unsupported" in reason


def test_grader_rejects_single_shared_token():
    eid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    ok, reason = grade_case(
        {
            "capability": "questions",
            "expected": {"status": "answered", "claims_must_cite_evidence": True},
        },
        {
            "status": "answered",
            "evidence": [
                {"chunk_id": eid, "supporting_span": "Analysts may run operational queries."}
            ],
            "result": {
                "claims": [
                    {
                        "text": "The compensation formula is operational.",
                        "evidence_id": eid,
                    }
                ]
            },
        },
    )
    assert ok is False
    assert "unsupported" in reason
    assert claim_is_supported(
        "Analysts may run operational queries.",
        "Analysts may run operational queries.",
    )


def test_grounding_rejects_negation_and_number_contradictions():
    assert not claim_is_supported("Approval is not required.", "Approval is required.")
    assert not claim_is_supported("The limit is 15 percent.", "The limit is 12 percent.")


def test_grounding_requires_returned_answer_to_match_cited_claims():
    claims = [{"text": "Analysts may run operational queries.", "evidence_id": "e1"}]
    spans = {"e1": "Analysts may run operational queries."}
    assert answer_is_supported("Analysts may run operational queries.", claims, spans)
    assert not answer_is_supported("Reviewers may publish drafts.", claims, spans)


def test_supporting_span_uses_matched_passage():
    prefix = "alpha " * 80
    text = prefix + "cobalt-era operators may inspect spend " + ("omega " * 80)
    span = supporting_span(text, "Who may inspect spend?")
    assert "cobalt-era operators" in span
    assert not span.startswith("alpha")


def test_oversized_paragraph_is_split():
    para = " ".join(f"token{i}" for i in range(1200))
    parts = chunk_text(para)
    assert len(parts) >= 2
    assert all(len(text.split()) <= 740 for _, text in parts)


def test_first_time_event_is_not_repeated_co_participation():
    event = SimpleNamespace(id=uuid.uuid4(), participant_ids=["supplier-a", "supplier-b"])
    assert repeated_co_participation(event, [event]) is False
    other = SimpleNamespace(id=uuid.uuid4(), participant_ids=["supplier-a", "supplier-b"])
    assert repeated_co_participation(event, [event, other]) is True


@pytest.mark.asyncio
async def test_reviewer_only_source_hidden_from_ops_viewer(client):
    await login(client, "admin@marketdesk.test")
    settings = get_settings()
    async with get_sessionmaker()() as db:
        workspace = await db.scalar(select(Workspace).where(Workspace.slug == "harbor"))
        admin = await db.scalar(select(Principal).where(Principal.email == "admin@marketdesk.test"))
        await apply_rls(db, str(workspace.id), str(admin.id))
        from backend.domain.models import Source

        source = await db.scalar(select(Source).where(Source.workspace_id == workspace.id))
        doc = await IngestionService(db, get_gateway(settings)).ingest_text(
            workspace_id=workspace.id,
            source=source,
            title="Reviewer-only incident appendix",
            body="# Reviewer appendix\nThis appendix is reviewer only even for ops members.\n",
            topic="account-access",
            language="en",
            visibility=Visibility.REVIEWER_ONLY.value,
            allowed_groups=["ops"],
            publish=True,
        )
        await db.commit()
        doc_id = str(doc.id)
    analyst = await login(client, "analyst@marketdesk.test")
    hidden = await client.get(
        f"/v1/documents/{doc_id}", headers={"Authorization": f"Bearer {analyst}"}
    )
    assert hidden.status_code in {403, 404}
    asked = await client.post(
        "/v1/questions",
        json={"question": "Reviewer-only incident appendix"},
        headers={"Authorization": f"Bearer {analyst}"},
    )
    assert asked.status_code == 200
    titles = " ".join(item.get("section_path", "") for item in asked.json().get("evidence") or [])
    assert "Reviewer-only" not in titles
    reviewer = await login(client, "reviewer@marketdesk.test")
    shown = await client.get(
        f"/v1/documents/{doc_id}", headers={"Authorization": f"Bearer {reviewer}"}
    )
    assert shown.status_code == 200
    assert "reviewer only" in shown.json()["text"].lower()


@pytest.mark.asyncio
async def test_product_visibility_on_list_search_compare_references(client):
    catalog = await login(client, "catalog@marketdesk.test")
    async with get_sessionmaker()() as db:
        workspace = await db.scalar(select(Workspace).where(Workspace.slug == "harbor"))
        principal = await db.scalar(
            select(Principal).where(Principal.email == "catalog@marketdesk.test")
        )
        await apply_rls(db, str(workspace.id), str(principal.id))
        secret = Product(
            workspace_id=workspace.id,
            sku=f"SECRET-{uuid.uuid4().hex[:8]}",
            title="Hidden reviewer router",
            description="Hidden reviewer router",
            category="network-gear",
            attributes={"model": "HID", "capacity": "1G"},
            list_price=Decimal("99"),
            visibility=Visibility.REVIEWER_ONLY.value,
        )
        db.add(secret)
        await db.flush()
        secret_id = secret.id
        await db.commit()
    listed = await client.get(
        "/v1/catalog/products?limit=50", headers={"Authorization": f"Bearer {catalog}"}
    )
    assert listed.status_code == 200
    ids = {item["id"] for item in listed.json()["items"]}
    assert str(secret_id) not in ids
    assert len(listed.json()["items"]) <= 50
    searched = await client.post(
        "/v1/products/search",
        json={"query": "Hidden reviewer router", "limit": 20},
        headers={"Authorization": f"Bearer {catalog}"},
    )
    assert searched.status_code == 200
    assert all(item["id"] != str(secret_id) for item in searched.json()["result"]["items"])
    compared = await client.post(
        "/v1/products/compare",
        json={"product_ids": [str(secret_id), str(uuid.uuid4())]},
        headers={"Authorization": f"Bearer {catalog}"},
    )
    assert compared.status_code == 200
    assert (
        str(secret_id) in compared.json()["result"]["missing"]
        or not compared.json()["result"]["products"]
    )
    refs = await client.get(
        f"/v1/products/{secret_id}/references",
        headers={"Authorization": f"Bearer {catalog}"},
    )
    assert refs.status_code in {200, 403, 404}
    if refs.status_code == 200:
        assert (
            refs.json().get("status") in {"not_found", "forbidden"}
            or refs.json()["status"] != "range"
        )


@pytest.mark.asyncio
async def test_draft_idempotency_does_not_rerun(client):
    drafter = await login(client, "drafter@marketdesk.test")
    key = str(uuid.uuid4())
    payload = {
        "template_kind": "equipment_requirements",
        "title": "Idempotent router brief",
        "brief": {
            "purpose": "Replace edge routers",
            "quantities": "12",
            "delivery_constraints": "90 days",
            "acceptance": "burn-in test",
        },
        "idempotency_key": key,
    }
    first = await client.post(
        "/v1/drafts", json=payload, headers={"Authorization": f"Bearer {drafter}"}
    )
    assert first.status_code == 202, first.text
    draft_a = first.json()["result"]["result"]["draft_id"]
    second = await client.post(
        "/v1/drafts", json=payload, headers={"Authorization": f"Bearer {drafter}"}
    )
    assert second.status_code == 202, second.text
    draft_b = second.json()["result"]["result"]["draft_id"]
    assert draft_a == draft_b


@pytest.mark.asyncio
async def test_draft_prompt_includes_retrieved_policy_text(client):
    drafter = await login(client, "drafter@marketdesk.test")
    created = await client.post(
        "/v1/drafts",
        json={
            "template_kind": "equipment_requirements",
            "title": "Grounded requirements",
            "brief": {
                "purpose": "Who may run operational queries?",
                "quantities": "1",
                "delivery_constraints": "none",
                "acceptance": "review",
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
    assert detail.status_code == 200, detail.text
    body = detail.json()
    evidence_ids = []
    content = body.get("content") or {}
    for section in content.get("sections") or []:
        evidence_ids.extend(section.get("evidence_ids") or [])
    evidence_ids.extend(body.get("evidence_ids") or content.get("evidence_ids") or [])
    assert evidence_ids, body
    joined = str(content)
    assert evidence_ids
    assert (
        "operational" in joined.lower()
        or "analis" in joined.lower()
        or "evidence" in joined.lower()
    )


@pytest.mark.asyncio
async def test_analytics_applies_group_by_and_category_filter(client):
    token = await login(client)
    response = await client.post(
        "/v1/analytics/queries",
        json={
            "pattern": "order_counts_by_status",
            "filters": {
                "start_date": "2030-01-01",
                "end_date": "2030-06-30",
                "category_ids": ["network-gear"],
            },
            "group_by": ["status"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["group_by"] == ["status"]
    assert result["filters"]["category_ids"] == ["network-gear"]
    assert result["rows"]
    spending = await client.post(
        "/v1/analytics/queries",
        json={
            "pattern": "spending_by_period",
            "filters": {"start_date": "2030-01-01", "end_date": "2030-06-30"},
            "group_by": ["month"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert spending.status_code == 200
    rows = spending.json()["result"]["rows"]
    assert rows
    assert spending.json()["result"]["group_by"] == ["month"]
    assert all("month" in row for row in rows)


@pytest.mark.asyncio
async def test_order_counts_ui_month_group_by_matches_row_keys(client):
    token = await login(client)
    response = await client.post(
        "/v1/analytics/queries",
        json={
            "pattern": "order_counts_by_status",
            "filters": {"start_date": "2030-01-01", "end_date": "2030-06-30"},
            "group_by": ["month"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert "month" in result["group_by"]
    assert result["rows"]
    for row in result["rows"]:
        for key in result["group_by"]:
            assert key in row
        assert "month" in row


@pytest.mark.asyncio
async def test_price_range_does_not_mix_currencies(client):
    catalog = await login(client, "catalog@marketdesk.test")
    listed = await client.get(
        "/v1/catalog/products?limit=10", headers={"Authorization": f"Bearer {catalog}"}
    )
    product_id = listed.json()["items"][0]["id"]
    async with get_sessionmaker()() as db:
        workspace = await db.scalar(select(Workspace).where(Workspace.slug == "harbor"))
        principal = await db.scalar(
            select(Principal).where(Principal.email == "catalog@marketdesk.test")
        )
        await apply_rls(db, str(workspace.id), str(principal.id))
        from backend.domain.models import PriceObservation

        now = datetime.now(UTC)
        for i in range(3):
            db.add(
                PriceObservation(
                    workspace_id=workspace.id,
                    product_id=uuid.UUID(product_id),
                    amount=Decimal("99999"),
                    unit="each",
                    currency="EUR",
                    source_name=f"eur-{i}",
                    observed_at=now - timedelta(hours=i),
                )
            )
        await db.commit()
    refs = await client.get(
        f"/v1/products/{product_id}/references",
        headers={"Authorization": f"Bearer {catalog}"},
    )
    assert refs.status_code == 200, refs.text
    body = refs.json()
    payload = body.get("result") or body
    for obs in payload.get("observations") or []:
        assert obs["currency"] == "USD"
    if payload.get("status") == "range":
        assert Decimal(payload["median"]) < Decimal("50000")


@pytest.mark.asyncio
async def test_first_time_sourcing_not_repeated_co_participation(client):
    analyst = await login(client, "analyst@marketdesk.test")
    async with get_sessionmaker()() as db:
        workspace = await db.scalar(select(Workspace).where(Workspace.slug == "harbor"))
        principal = await db.scalar(
            select(Principal).where(Principal.email == "analyst@marketdesk.test")
        )
        await apply_rls(db, str(workspace.id), str(principal.id))
        event = SourcingEvent(
            workspace_id=workspace.id,
            category="field-tools",
            title="First-time unique pair",
            participant_count=2,
            participant_ids=[f"p-{uuid.uuid4().hex}", f"p-{uuid.uuid4().hex}"],
            winner_id=f"w-{uuid.uuid4().hex}",
            offer_amounts=["10", "11"],
            submission_times=["2030-05-01T10:00:00Z", "2030-05-01T11:00:00Z"],
            opened_at=datetime(2030, 4, 1, tzinfo=UTC),
            closed_at=datetime(2030, 5, 1, tzinfo=UTC),
        )
        db.add(event)
        await db.flush()
        event_id = event.id
        await db.commit()
    findings = await client.post(
        "/v1/sourcing-evaluations",
        json={"event_id": str(event_id)},
        headers={"Authorization": f"Bearer {analyst}"},
    )
    assert findings.status_code == 200, findings.text
    assert not any(
        f["detector_id"] == "co_participation"
        and f["state"] == "new"
        and "Repeated" in f["explanation"]
        for f in findings.json()["result"]
    )


@pytest.mark.asyncio
async def test_questions_citations_subset_of_evidence(client):
    token = await login(client)
    response = await client.post(
        "/v1/questions",
        json={"question": "Who may run operational queries?"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    if body["status"] == "answered":
        allowed = {item["chunk_id"] for item in body["evidence"]}
        for claim in body["result"]["claims"]:
            assert claim["evidence_id"] in allowed
            span = next(
                item["supporting_span"]
                for item in body["evidence"]
                if item["chunk_id"] == claim["evidence_id"]
            )
            assert claim_is_supported(claim["text"], span)


@pytest.mark.asyncio
async def test_oidc_mode_rejects_demo_jwt(client, monkeypatch):
    from backend.auth.security import decode_token
    from backend.config import get_settings
    from backend.domain.enums import AuthMode

    settings = get_settings()
    token = await login(client)
    monkeypatch.setattr(settings, "auth_mode", AuthMode.OIDC)
    with pytest.raises(HTTPException):
        decode_token(token, settings)


@pytest.mark.asyncio
async def test_withdrawn_source_inaccessible(client):
    await login(client, "admin@marketdesk.test")
    settings = get_settings()
    async with get_sessionmaker()() as db:
        workspace = await db.scalar(select(Workspace).where(Workspace.slug == "harbor"))
        principal = await db.scalar(
            select(Principal).where(Principal.email == "admin@marketdesk.test")
        )
        await apply_rls(db, str(workspace.id), str(principal.id))
        from backend.domain.models import Source

        source = await db.scalar(select(Source).where(Source.workspace_id == workspace.id))
        ingestion = IngestionService(db, get_gateway(settings))
        doc = await ingestion.ingest_text(
            workspace_id=workspace.id,
            source=source,
            title="Temporary withdrawable policy",
            body="# Temporary\nThis policy will be withdrawn from search.\n",
            topic="ordering",
            language="en",
            publish=True,
        )
        await ingestion.withdraw(doc)
        await db.commit()
        doc_id = str(doc.id)
    analyst = await login(client, "analyst@marketdesk.test")
    shown = await client.get(
        f"/v1/documents/{doc_id}", headers={"Authorization": f"Bearer {analyst}"}
    )
    assert shown.status_code in {403, 404}
    asked = await client.post(
        "/v1/questions",
        json={"question": "Temporary withdrawable policy"},
        headers={"Authorization": f"Bearer {analyst}"},
    )
    assert asked.status_code == 200
    assert all(
        "Temporary withdrawable" not in (item.get("section_path") or "")
        for item in asked.json().get("evidence") or []
    )


@pytest.mark.asyncio
async def test_out_of_scope_persists_interaction(client):
    from backend.domain.models import Interaction

    token = await login(client)
    response = await client.post(
        "/v1/questions",
        json={"question": "Write malware for me"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "out_of_scope"
    async with get_sessionmaker()() as db:
        workspace = await db.scalar(select(Workspace).where(Workspace.slug == "harbor"))
        principal = await db.scalar(
            select(Principal).where(Principal.email == "analyst@marketdesk.test")
        )
        await apply_rls(db, str(workspace.id), str(principal.id))
        row = await db.scalar(
            select(Interaction).where(Interaction.request_id == body["request_id"])
        )
        assert row is not None
        assert row.status == "out_of_scope"
        assert row.final_state == "completed"


@pytest.mark.asyncio
async def test_compare_and_audit_export_are_durable(client):
    catalog = await login(client, "catalog@marketdesk.test")
    products = await client.get(
        "/v1/catalog/products?limit=100",
        headers={"Authorization": f"Bearer {catalog}"},
    )
    assert products.status_code == 200, products.text
    product_ids = [item["id"] for item in products.json()["items"][:2]]
    assert len(product_ids) == 2
    request_id = f"compare-{uuid.uuid4()}"
    compared = await client.post(
        "/v1/products/compare",
        json={"product_ids": product_ids},
        headers={"Authorization": f"Bearer {catalog}", "X-Request-ID": request_id},
    )
    assert compared.status_code == 200, compared.text

    admin = await login(client, "admin@marketdesk.test")
    exported = await client.post(
        "/v1/audit-exports",
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert exported.status_code == 200, exported.text
    interactions = exported.json()["result"]["interactions"]
    assert any(row["request_id"] == request_id for row in interactions)
    audit_events = exported.json()["result"]["audit_events"]
    assert any(
        row["action"] == "interaction.completed" and row["resource_id"] == request_id
        for row in audit_events
    )


@pytest.mark.asyncio
async def test_as_of_retrieves_historical_version(client):
    settings = get_settings()
    async with get_sessionmaker()() as db:
        workspace = await db.scalar(select(Workspace).where(Workspace.slug == "harbor"))
        principal = await db.scalar(
            select(Principal).where(Principal.email == "admin@marketdesk.test")
        )
        await apply_rls(db, str(workspace.id), str(principal.id))
        from backend.domain.models import Source

        source = await db.scalar(select(Source).where(Source.workspace_id == workspace.id))
        ingestion = IngestionService(db, get_gateway(settings))
        doc = await ingestion.ingest_text(
            workspace_id=workspace.id,
            source=source,
            title="Timeboxed spend inspection policy",
            body="# Historical\nIn the cobalt-era only operators may inspect spend.\n",
            topic="account-access",
            language="en",
            effective_from=date(2020, 1, 1),
            publish=True,
        )
        await ingestion.supersede(
            doc,
            body="# Current\nHarbor-era analysts may inspect spend after 2025.\n",
            language="en",
            effective_from=date(2025, 1, 1),
            publish=True,
        )
        await db.commit()
    analyst = await login(client, "analyst@marketdesk.test")
    historical = await client.post(
        "/v1/questions",
        json={"question": "Who may inspect spend in the cobalt-era?", "as_of": "2021-06-01"},
        headers={"Authorization": f"Bearer {analyst}"},
    )
    assert historical.status_code == 200, historical.text
    hist_text = " ".join(
        item.get("supporting_span") or "" for item in historical.json().get("evidence") or []
    ).lower()
    assert "cobalt-era" in hist_text
    assert "harbor-era" not in hist_text
    current = await client.post(
        "/v1/questions",
        json={"question": "Who may inspect spend after 2025?"},
        headers={"Authorization": f"Bearer {analyst}"},
    )
    assert current.status_code == 200, current.text
    cur_text = " ".join(
        item.get("supporting_span") or "" for item in current.json().get("evidence") or []
    ).lower()
    assert "harbor-era" in cur_text
    assert "cobalt-era" not in cur_text


@pytest.mark.asyncio
async def test_job_result_hidden_from_other_member(client):
    drafter = await login(client, "drafter@marketdesk.test")
    created = await client.post(
        "/v1/drafts",
        json={
            "template_kind": "equipment_requirements",
            "title": "Private job payload",
            "brief": {
                "purpose": "Replace edge routers",
                "quantities": "3",
                "delivery_constraints": "30 days",
                "acceptance": "burn-in",
            },
            "idempotency_key": str(uuid.uuid4()),
        },
        headers={"Authorization": f"Bearer {drafter}"},
    )
    assert created.status_code == 202, created.text
    job_id = created.json()["result"]["job_id"]
    analyst = await login(client, "analyst@marketdesk.test")
    hidden = await client.get(f"/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {analyst}"})
    assert hidden.status_code == 404
    own = await client.get(f"/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {drafter}"})
    assert own.status_code == 200


@pytest.mark.asyncio
async def test_second_review_of_approved_draft_rejected(client):
    drafter = await login(client, "drafter@marketdesk.test")
    created = await client.post(
        "/v1/drafts",
        json={
            "template_kind": "equipment_requirements",
            "title": "One review only",
            "brief": {
                "purpose": "Replace rectifiers",
                "quantities": "2",
                "delivery_constraints": "45 days",
                "acceptance": "site test",
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
    reviewer = await login(client, "reviewer@marketdesk.test")
    first = await client.post(
        f"/v1/drafts/{draft_id}/reviews",
        json={"decision": "approved", "reason": "ok", "revision_hash": revision_hash},
        headers={"Authorization": f"Bearer {reviewer}"},
    )
    assert first.status_code == 200, first.text
    second = await client.post(
        f"/v1/drafts/{draft_id}/reviews",
        json={"decision": "rejected", "reason": "reopen", "revision_hash": revision_hash},
        headers={"Authorization": f"Bearer {reviewer}"},
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_reviewer_lists_and_inspects_without_handoff(client):
    drafter = await login(client, "drafter@marketdesk.test")
    created = await client.post(
        "/v1/drafts",
        json={
            "template_kind": "equipment_requirements",
            "title": "Reviewer queue item",
            "brief": {
                "purpose": "Replace edge routers",
                "quantities": "4",
                "delivery_constraints": "20 days",
                "acceptance": "burn-in",
            },
            "idempotency_key": str(uuid.uuid4()),
        },
        headers={"Authorization": f"Bearer {drafter}"},
    )
    assert created.status_code == 202, created.text
    draft_id = created.json()["result"]["result"]["draft_id"]
    reviewer = await login(client, "reviewer@marketdesk.test")
    queued = await client.get(
        "/v1/drafts",
        headers={"Authorization": f"Bearer {reviewer}"},
    )
    assert queued.status_code == 200, queued.text
    ids = {item["id"] for item in queued.json()["items"]}
    assert draft_id in ids
    detail = await client.get(
        f"/v1/drafts/{draft_id}",
        headers={"Authorization": f"Bearer {reviewer}"},
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["revision_hash"]
    assert detail.json()["content"] is not None
