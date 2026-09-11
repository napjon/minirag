from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from jwt.algorithms import RSAAlgorithm

import backend.auth.security as security
from backend.config import Settings
from backend.domain.enums import AuthMode


def _oidc_fixture() -> tuple[object, dict, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": "test-key", "alg": "RS256", "use": "sig"})
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "iss": "https://identity.example.test",
            "aud": "marketdesk-api",
            "sub": "oidc-user@example.test",
            "workspace_id": "00000000-0000-0000-0000-000000000001",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    return private_key, {"keys": [public_jwk]}, token


@pytest.mark.asyncio
async def test_oidc_token_is_verified_against_configured_jwks(monkeypatch):
    _, jwks, token = _oidc_fixture()
    settings = Settings(
        _env_file=None,
        auth_mode=AuthMode.OIDC,
        oidc_issuer="https://identity.example.test",
        oidc_audience="marketdesk-api",
        oidc_jwks_url="https://identity.example.test/jwks",
    )

    async def fake_jwks(_settings):
        return jwks

    monkeypatch.setattr(security, "_fetch_oidc_jwks", fake_jwks)
    claims = await security.decode_access_token(token, settings)
    assert claims["sub"] == "oidc-user@example.test"


@pytest.mark.asyncio
async def test_oidc_token_rejects_wrong_issuer(monkeypatch):
    _, jwks, token = _oidc_fixture()
    settings = Settings(
        _env_file=None,
        auth_mode=AuthMode.OIDC,
        oidc_issuer="https://other-identity.example.test",
        oidc_audience="marketdesk-api",
        oidc_jwks_url="https://identity.example.test/jwks",
    )

    async def fake_jwks(_settings):
        return jwks

    monkeypatch.setattr(security, "_fetch_oidc_jwks", fake_jwks)
    with pytest.raises(HTTPException) as exc:
        await security.decode_access_token(token, settings)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_oidc_token_rejects_unknown_key(monkeypatch):
    _, _, token = _oidc_fixture()
    settings = Settings(
        _env_file=None,
        auth_mode=AuthMode.OIDC,
        oidc_issuer="https://identity.example.test",
        oidc_audience="marketdesk-api",
        oidc_jwks_url="https://identity.example.test/jwks",
    )

    async def fake_jwks(_settings):
        return {"keys": []}

    monkeypatch.setattr(security, "_fetch_oidc_jwks", fake_jwks)
    with pytest.raises(HTTPException) as exc:
        await security.decode_access_token(token, settings)
    assert exc.value.status_code == 401
