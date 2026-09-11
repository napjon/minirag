from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from backend.db import apply_rls, get_sessionmaker
from backend.domain.models import Principal, SourcingEvent, SpendRecord, Workspace
from tests.conftest import login

SPEND_FILTERS = {"start_date": "2030-01-01", "end_date": "2030-06-30"}


@pytest.mark.asyncio
async def test_order_counts_month_group_by_is_honored(client):
    token = await login(client)
    response = await client.post(
        "/v1/analytics/queries",
        json={
            "pattern": "order_counts_by_status",
            "filters": SPEND_FILTERS,
            "group_by": ["month"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert "month" in result["group_by"]
    assert result["rows"]
    assert all("month" in row for row in result["rows"])


@pytest.mark.asyncio
async def test_spending_freshness_comes_from_source_dates(client):
    token = await login(client)
    response = await client.post(
        "/v1/analytics/queries",
        json={
            "pattern": "spending_by_period",
            "filters": SPEND_FILTERS,
            "group_by": ["month"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["group_by"] == ["month"]
    freshness = result["freshness"]
    assert isinstance(freshness, str)
    date.fromisoformat(freshness[:10])
    assert freshness[:10] != SPEND_FILTERS["end_date"]
    assert freshness[:10] == "2030-06-28"


@pytest.mark.asyncio
async def test_spending_excludes_other_currency(client):
    token = await login(client)
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "pattern": "spending_by_period",
        "filters": SPEND_FILTERS,
        "group_by": ["month"],
    }
    before = await client.post("/v1/analytics/queries", json=payload, headers=headers)
    assert before.status_code == 200, before.text
    before_sum = sum(Decimal(row["amount"]) for row in before.json()["result"]["rows"])
    async with get_sessionmaker()() as db:
        workspace = await db.scalar(select(Workspace).where(Workspace.slug == "harbor"))
        principal = await db.scalar(
            select(Principal).where(Principal.email == "analyst@marketdesk.test")
        )
        assert workspace is not None and principal is not None
        await apply_rls(db, str(workspace.id), str(principal.id))
        db.add(
            SpendRecord(
                workspace_id=workspace.id,
                period_start=date(2030, 3, 1),
                period_end=date(2030, 3, 28),
                category="network-gear",
                supplier_id="supplier-eur",
                amount=Decimal("999999"),
                currency="EUR",
                source_revision=1,
            )
        )
        await db.commit()
    after = await client.post("/v1/analytics/queries", json=payload, headers=headers)
    assert after.status_code == 200, after.text
    rows = after.json()["result"]["rows"]
    after_sum = sum(Decimal(row["amount"]) for row in rows)
    assert after_sum == before_sum
    assert all(Decimal(row["amount"]) != Decimal("999999") for row in rows)


@pytest.mark.asyncio
async def test_restricted_viewer_cannot_run_analytics(client):
    token = await login(client, "restricted@marketdesk.test")
    response = await client.post(
        "/v1/analytics/queries",
        json={
            "pattern": "spending_by_period",
            "filters": SPEND_FILTERS,
            "group_by": ["month"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    body = response.json()
    assert "rows" not in body
    result = body.get("result")
    assert not (isinstance(result, dict) and result.get("rows"))


@pytest.mark.asyncio
async def test_sourcing_date_filter_includes_events_on_end_date(client):
    async with get_sessionmaker()() as db:
        workspace = await db.scalar(select(Workspace).where(Workspace.slug == "harbor"))
        principal = await db.scalar(
            select(Principal).where(Principal.email == "analyst@marketdesk.test")
        )
        assert workspace is not None and principal is not None
        await apply_rls(db, str(workspace.id), str(principal.id))
        db.add(
            SourcingEvent(
                workspace_id=workspace.id,
                category="network-gear",
                title=f"End-date event {datetime.now(UTC).timestamp()}",
                participant_count=3,
                participant_ids=["supplier-a", "supplier-b", "supplier-c"],
                winner_id="supplier-a",
                offer_amounts=["100", "105", "110"],
                submission_times=[
                    "2030-06-30T08:00:00Z",
                    "2030-06-30T09:00:00Z",
                    "2030-06-30T10:00:00Z",
                ],
                opened_at=datetime(2030, 6, 30, 8, tzinfo=UTC),
                closed_at=datetime(2030, 6, 30, 18, tzinfo=UTC),
                outcome="awarded",
            )
        )
        await db.commit()
    token = await login(client, "analyst@marketdesk.test")
    response = await client.post(
        "/v1/analytics/queries",
        json={
            "pattern": "sourcing_outcomes",
            "filters": {"start_date": "2030-06-30", "end_date": "2030-06-30"},
            "group_by": ["month"],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["result"]["row_count"] >= 1
