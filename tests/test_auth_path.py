from __future__ import annotations

import jwt
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

import backend.auth.security as security
from backend.auth.security import decode_token
from backend.config import get_settings
from backend.db import apply_rls, get_sessionmaker
from backend.domain.enums import AuthMode
from backend.domain.models import Membership, Principal, Workspace
from tests.conftest import login


@pytest.mark.asyncio
async def test_demo_login_works_in_demo_mode(client):
    response = await client.post(
        "/v1/auth/demo",
        json={"email": "analyst@marketdesk.test", "workspace": "harbor"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token"]
    me = await client.get("/v1/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200, me.text
    assert me.json()["email"] == "analyst@marketdesk.test"


@pytest.mark.asyncio
async def test_decode_token_rejects_demo_jwt_when_auth_mode_is_not_demo(client, monkeypatch):
    settings = get_settings()
    token = await login(client)
    monkeypatch.setattr(settings, "auth_mode", AuthMode.OIDC)
    with pytest.raises(HTTPException) as exc:
        decode_token(token, settings)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_oidc_mode_rejects_demo_bearer_on_questions(client, monkeypatch):
    token = await login(client)
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_mode", AuthMode.OIDC)
    response = await client.post(
        "/v1/questions",
        json={"question": "Who may run operational queries?"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_malformed_uuid_claim_is_a_401_not_a_server_error(client):
    token = await login(client)
    settings = get_settings()
    payload = jwt.decode(token, options={"verify_signature": False})
    payload["principal_id"] = "not-a-uuid"
    malformed = jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    response = await client.get(
        "/v1/me",
        headers={"Authorization": f"Bearer {malformed}"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_oidc_subject_resolves_local_principal_and_membership(client, monkeypatch):
    demo_token = await login(client)
    claims = jwt.decode(demo_token, options={"verify_signature": False})

    async def verified_oidc_token(_token, _settings):
        return {
            "sub": claims["sub"],
            "workspace_id": claims["workspace_id"],
        }

    settings = get_settings()
    monkeypatch.setattr(settings, "auth_mode", AuthMode.OIDC)
    monkeypatch.setattr(security, "decode_access_token", verified_oidc_token)
    response = await client.get("/v1/me", headers={"Authorization": "Bearer opaque-oidc-token"})
    assert response.status_code == 200, response.text
    assert response.json()["email"] == "analyst@marketdesk.test"
    assert "analytics" in response.json()["capabilities"]


@pytest.mark.asyncio
async def test_runtime_role_requires_and_accepts_transaction_rls_context(app):
    async with get_sessionmaker()() as db:
        workspace = await db.scalar(select(Workspace).where(Workspace.slug == "harbor"))
        principal = await db.scalar(
            select(Principal).where(Principal.email == "analyst@marketdesk.test")
        )
        assert workspace is not None and principal is not None
        workspace_id = workspace.id
        principal_id = principal.id
        without_context = await db.scalar(select(func.count()).select_from(Membership))
        assert without_context == 0
        await db.rollback()
        await apply_rls(db, str(workspace_id), str(principal_id))
        with_context = await db.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.workspace_id == workspace_id)
        )
        assert with_context >= 1
