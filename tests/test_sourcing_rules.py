from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from backend.auth.security import AuthContext
from backend.db import apply_rls, get_sessionmaker
from backend.detection.service import RULES, DetectionService
from backend.domain.enums import FindingState, Role
from backend.domain.models import Membership, Principal, SourcingEvent, Workspace
from tests.conftest import login


def _rule(rule_id: str) -> dict:
    return next(item for item in RULES if item["rule_id"] == rule_id)


@asynccontextmanager
async def analyst_session():
    async with get_sessionmaker()() as db:
        workspace = await db.scalar(select(Workspace).where(Workspace.slug == "harbor"))
        principal = await db.scalar(
            select(Principal).where(Principal.email == "analyst@marketdesk.test")
        )
        assert workspace is not None and principal is not None
        await apply_rls(db, str(workspace.id), str(principal.id))
        membership = await db.scalar(
            select(Membership).where(
                Membership.principal_id == principal.id,
                Membership.workspace_id == workspace.id,
            )
        )
        assert membership is not None
        auth = AuthContext(
            principal_id=principal.id,
            workspace_id=workspace.id,
            subject=principal.subject,
            email=principal.email,
            display_name=principal.display_name,
            roles=tuple(Role(role) for role in membership.roles),
            group_ids=tuple(membership.group_ids or []),
            permission_fingerprint="test",
        )
        try:
            yield db, auth, workspace
        finally:
            await db.rollback()


def test_low_participation_predicate():
    rule = _rule("low_participation")
    assert rule["predicate"](SimpleNamespace(participant_count=2))
    assert rule["predicate"](SimpleNamespace(participant_count=0))
    assert not rule["predicate"](SimpleNamespace(participant_count=3))


@pytest.mark.asyncio
async def test_low_participation_event_produces_finding(app):
    async with analyst_session() as (db, auth, _workspace):
        event = await db.scalar(
            select(SourcingEvent).where(SourcingEvent.title == "Edge router replenishment")
        )
        assert event is not None
        assert event.participant_count < 3
        findings = await DetectionService(db).sourcing_eval(auth, event.id)
        low = [item for item in findings if item.detector_id == "low_participation"]
        assert low
        assert all(item.state != FindingState.NOT_EVALUABLE.value for item in low)
        assert all("low participation" in item.explanation.lower() for item in low)


@pytest.mark.asyncio
async def test_missing_sample_size_yields_not_evaluable(app):
    async with analyst_session() as (db, auth, workspace):
        event = SourcingEvent(
            workspace_id=workspace.id,
            category="network-gear",
            title="Incomplete sample event",
            participant_count=5,
            participant_ids=["supplier-a"],
            winner_id="supplier-z",
            offer_amounts=["4100"],
            submission_times=["2030-04-01T09:00:00Z"],
            opened_at=datetime(2030, 3, 1, tzinfo=UTC),
            closed_at=datetime(2030, 4, 1, tzinfo=UTC),
        )
        db.add(event)
        await db.flush()
        findings = await DetectionService(db).sourcing_eval(auth, event.id)
        by_id = {item.detector_id: item for item in findings}
        assert "low_participation" not in by_id
        for rule_id in ("submission_clustering", "offer_deviation"):
            finding = by_id[rule_id]
            assert finding.state == FindingState.NOT_EVALUABLE.value
            assert "not_evaluable" in finding.explanation
            assert "sample size" in finding.explanation


@pytest.mark.asyncio
async def test_seeded_low_participation_event_via_http(client):
    token = await login(client, "analyst@marketdesk.test")
    headers = {"Authorization": f"Bearer {token}"}
    events = await client.get("/v1/catalog/events", headers=headers)
    assert events.status_code == 200, events.text
    event = next(item for item in events.json()["items"] if item["participant_count"] < 3)
    response = await client.post(
        "/v1/sourcing-evaluations",
        json={"event_id": event["id"]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    findings = response.json()["result"]
    assert any(item["detector_id"] == "low_participation" for item in findings)
    assert any(
        item["state"] == FindingState.NOT_EVALUABLE.value
        and item["detector_id"] in {"submission_clustering", "offer_deviation"}
        for item in findings
    )
