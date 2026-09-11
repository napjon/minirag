from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from backend.db import apply_rls, get_sessionmaker
from backend.domain.enums import Visibility
from backend.domain.models import DetectionFinding, Principal, Product, SourcingEvent, Workspace
from tests.conftest import login


@pytest.mark.asyncio
async def test_catalog_listing_check_hides_reviewer_only_product(client):
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
            attributes={},
            list_price=Decimal("99"),
            visibility=Visibility.REVIEWER_ONLY.value,
        )
        db.add(secret)
        await db.flush()
        secret_id = secret.id
        await db.commit()
    response = await client.post(
        "/v1/listing-checks",
        json={"product_id": str(secret_id)},
        headers={"Authorization": f"Bearer {catalog}"},
    )
    assert response.status_code in {200, 404}, response.text
    if response.status_code == 200:
        assert response.json()["result"] == []
    async with get_sessionmaker()() as db:
        workspace = await db.scalar(select(Workspace).where(Workspace.slug == "harbor"))
        principal = await db.scalar(
            select(Principal).where(Principal.email == "catalog@marketdesk.test")
        )
        await apply_rls(db, str(workspace.id), str(principal.id))
        rows = list(
            (
                await db.scalars(
                    select(DetectionFinding).where(DetectionFinding.entity_id == secret_id)
                )
            ).all()
        )
        assert rows == []


@pytest.mark.asyncio
async def test_repeat_listing_check_does_not_duplicate_spec_consistency(client):
    catalog = await login(client, "catalog@marketdesk.test")
    headers = {"Authorization": f"Bearer {catalog}"}
    async with get_sessionmaker()() as db:
        workspace = await db.scalar(select(Workspace).where(Workspace.slug == "harbor"))
        principal = await db.scalar(
            select(Principal).where(Principal.email == "catalog@marketdesk.test")
        )
        await apply_rls(db, str(workspace.id), str(principal.id))
        product = Product(
            workspace_id=workspace.id,
            sku=f"SPEC-{uuid.uuid4().hex[:8]}",
            title="Incomplete listing for duplicate check",
            description="Missing required attributes",
            category="network-gear",
            attributes={},
            list_price=Decimal("50"),
            visibility=Visibility.PUBLIC_WORKSPACE.value,
        )
        db.add(product)
        await db.flush()
        product_id = product.id
        await db.commit()
    payload = {"product_id": str(product_id)}
    first = await client.post("/v1/listing-checks", json=payload, headers=headers)
    second = await client.post("/v1/listing-checks", json=payload, headers=headers)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert any(item["detector_id"] == "spec_consistency" for item in first.json()["result"])
    async with get_sessionmaker()() as db:
        workspace = await db.scalar(select(Workspace).where(Workspace.slug == "harbor"))
        principal = await db.scalar(
            select(Principal).where(Principal.email == "catalog@marketdesk.test")
        )
        await apply_rls(db, str(workspace.id), str(principal.id))
        rows = list(
            (
                await db.scalars(
                    select(DetectionFinding).where(
                        DetectionFinding.entity_id == product_id,
                        DetectionFinding.detector_id == "spec_consistency",
                    )
                )
            ).all()
        )
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_repeat_listing_check_same_idempotency_key_returns_same_ids(client):
    catalog = await login(client, "catalog@marketdesk.test")
    headers = {"Authorization": f"Bearer {catalog}"}
    async with get_sessionmaker()() as db:
        workspace = await db.scalar(select(Workspace).where(Workspace.slug == "harbor"))
        principal = await db.scalar(
            select(Principal).where(Principal.email == "catalog@marketdesk.test")
        )
        await apply_rls(db, str(workspace.id), str(principal.id))
        product = Product(
            workspace_id=workspace.id,
            sku=f"IDEM-{uuid.uuid4().hex[:8]}",
            title="Incomplete listing for idempotency",
            description="Missing required attributes",
            category="network-gear",
            attributes={},
            list_price=Decimal("50"),
            visibility=Visibility.PUBLIC_WORKSPACE.value,
        )
        db.add(product)
        await db.flush()
        product_id = product.id
        await db.commit()
    payload = {"product_id": str(product_id), "idempotency_key": str(uuid.uuid4())}
    first = await client.post("/v1/listing-checks", json=payload, headers=headers)
    second = await client.post("/v1/listing-checks", json=payload, headers=headers)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    first_ids = [item["id"] for item in first.json()["result"]]
    second_ids = [item["id"] for item in second.json()["result"]]
    assert first_ids
    assert first_ids == second_ids


@pytest.mark.asyncio
async def test_first_time_sourcing_ignores_later_co_participation_sibling(client):
    analyst = await login(client, "analyst@marketdesk.test")
    pair = [f"p-{uuid.uuid4().hex}", f"p-{uuid.uuid4().hex}"]
    async with get_sessionmaker()() as db:
        workspace = await db.scalar(select(Workspace).where(Workspace.slug == "harbor"))
        principal = await db.scalar(
            select(Principal).where(Principal.email == "analyst@marketdesk.test")
        )
        await apply_rls(db, str(workspace.id), str(principal.id))
        event = SourcingEvent(
            workspace_id=workspace.id,
            category="field-tools",
            title="Earlier unique pair",
            participant_count=2,
            participant_ids=pair,
            winner_id=pair[0],
            offer_amounts=["10", "11"],
            submission_times=["2030-05-01T10:00:00Z", "2030-05-01T11:00:00Z"],
            opened_at=datetime(2030, 4, 1, tzinfo=UTC),
            closed_at=datetime(2030, 5, 1, tzinfo=UTC),
        )
        future = SourcingEvent(
            workspace_id=workspace.id,
            category="field-tools",
            title="Later unique pair",
            participant_count=2,
            participant_ids=pair,
            winner_id=pair[0],
            offer_amounts=["12", "13"],
            submission_times=["2030-06-01T10:00:00Z", "2030-06-01T11:00:00Z"],
            opened_at=datetime(2030, 5, 15, tzinfo=UTC),
            closed_at=datetime(2030, 6, 1, tzinfo=UTC),
        )
        db.add(event)
        db.add(future)
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
        item["detector_id"] == "co_participation"
        and item["state"] == "new"
        and "Repeated" in item["explanation"]
        for item in findings.json()["result"]
    )
