from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import Settings, get_settings
from backend.db import apply_rls, get_sessionmaker
from backend.domain.enums import AuthMode, Role
from backend.domain.models import Membership, Principal, Workspace

OIDC_ALGORITHMS = {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"}
_oidc_jwks_cache: dict[str, tuple[float, dict[str, Any]]] = {}

CAPABILITIES: dict[str, set[Role]] = {
    "questions": {
        Role.VIEWER,
        Role.ANALYST,
        Role.DRAFTER,
        Role.REVIEWER,
        Role.ADMIN,
        Role.CATALOG_EDITOR,
    },
    "analytics": {Role.ANALYST, Role.ADMIN},
    "products.search": {
        Role.VIEWER,
        Role.ANALYST,
        Role.CATALOG_EDITOR,
        Role.ADMIN,
        Role.DRAFTER,
        Role.REVIEWER,
    },
    "products.compare": {
        Role.VIEWER,
        Role.ANALYST,
        Role.CATALOG_EDITOR,
        Role.ADMIN,
        Role.DRAFTER,
        Role.REVIEWER,
    },
    "products.references": {Role.ANALYST, Role.CATALOG_EDITOR, Role.ADMIN},
    "listing_checks": {Role.CATALOG_EDITOR, Role.ADMIN, Role.REVIEWER},
    "sourcing": {Role.ANALYST, Role.ADMIN, Role.REVIEWER},
    "drafts.create": {Role.DRAFTER, Role.ADMIN},
    "drafts.read": {Role.DRAFTER, Role.REVIEWER, Role.ADMIN},
    "drafts.review": {Role.REVIEWER, Role.ADMIN},
    "drafts.export": {Role.DRAFTER, Role.REVIEWER, Role.ADMIN},
    "feedback": {
        Role.VIEWER,
        Role.ANALYST,
        Role.CATALOG_EDITOR,
        Role.DRAFTER,
        Role.REVIEWER,
        Role.ADMIN,
    },
    "sources.read": {
        Role.VIEWER,
        Role.ANALYST,
        Role.DRAFTER,
        Role.REVIEWER,
        Role.ADMIN,
        Role.CATALOG_EDITOR,
    },
    "sources.ingest": {Role.ADMIN, Role.CATALOG_EDITOR},
    "sources.review": {Role.ADMIN, Role.REVIEWER},
    "audit.export": {Role.ADMIN},
    "admin": {Role.ADMIN},
}


@dataclass(frozen=True)
class AuthContext:
    principal_id: UUID
    workspace_id: UUID
    subject: str
    email: str
    display_name: str
    roles: tuple[Role, ...]
    group_ids: tuple[str, ...]
    permission_fingerprint: str

    def can(self, capability: str) -> bool:
        allowed = CAPABILITIES.get(capability, set())
        return any(role in allowed for role in self.roles)


def issue_token(
    *,
    settings: Settings,
    principal: Principal,
    workspace: Workspace,
    roles: list[Role],
    group_ids: list[str],
) -> str:
    now = datetime.now(UTC)
    payload = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": principal.subject,
        "principal_id": str(principal.id),
        "workspace_id": str(workspace.id),
        "email": principal.email,
        "name": principal.display_name,
        "roles": [r.value for r in roles],
        "groups": group_ids,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=12)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm="HS256")


def decode_token(token: str, settings: Settings) -> dict:
    if settings.auth_mode != AuthMode.DEMO:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "demo tokens are disabled")
    try:
        return jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from exc


async def _fetch_oidc_jwks(settings: Settings) -> dict[str, Any]:
    if not settings.oidc_jwks_url:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "OIDC JWKS is not configured")
    now = time.monotonic()
    cached = _oidc_jwks_cache.get(settings.oidc_jwks_url)
    if cached is not None and cached[0] > now:
        return cached[1]
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(settings.oidc_jwks_url)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "OIDC keys are unavailable"
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "OIDC keys are invalid")
    ttl = max(1, settings.oidc_jwks_cache_seconds)
    _oidc_jwks_cache[settings.oidc_jwks_url] = (now + ttl, payload)
    return payload


async def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    if settings.auth_mode == AuthMode.DEMO:
        return decode_token(token, settings)
    try:
        header = jwt.get_unverified_header(token)
        algorithm = str(header.get("alg") or "")
        key_id = str(header.get("kid") or "")
        if algorithm not in OIDC_ALGORITHMS or not key_id:
            raise InvalidTokenError("unsupported OIDC token header")
        if not settings.oidc_issuer or not (settings.oidc_audience or settings.jwt_audience):
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "OIDC is not configured")
        jwks = await _fetch_oidc_jwks(settings)
        matches = [key for key in jwks["keys"] if str(key.get("kid") or "") == key_id]
        if len(matches) != 1:
            raise InvalidTokenError("OIDC signing key was not found")
        signing_key = jwt.PyJWK.from_dict(matches[0], algorithm=algorithm).key
        return jwt.decode(
            token,
            signing_key,
            algorithms=[algorithm],
            audience=settings.oidc_audience or settings.jwt_audience,
            issuer=settings.oidc_issuer,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token") from exc


def _token_uuid(payload: dict, claim: str) -> UUID:
    """Parse a required UUID claim without allowing malformed tokens to 500."""
    try:
        return UUID(str(payload[claim]))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token claims") from exc


def _membership_roles(values: object) -> tuple[Role, ...]:
    if not isinstance(values, list):
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "invalid membership configuration"
        )
    try:
        return tuple(Role(str(value)) for value in values)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "invalid membership configuration"
        ) from exc


def _membership_groups(values: object) -> tuple[str, ...]:
    if values is None:
        return ()
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "invalid membership configuration"
        )
    return tuple(values)


async def get_db() -> AsyncSession:
    async with get_sessionmaker()() as session:
        yield session


async def get_auth(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    payload = await decode_access_token(authorization.split(" ", 1)[1], settings)
    workspace_id = _token_uuid(payload, "workspace_id")
    if settings.auth_mode == AuthMode.OIDC:
        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token claims")
        principal = await db.scalar(select(Principal).where(Principal.subject == subject))
        if principal is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown principal")
        principal_id = principal.id
    else:
        principal_id = _token_uuid(payload, "principal_id")
        principal = None
    await apply_rls(db, str(workspace_id), str(principal_id))
    membership = await db.scalar(
        select(Membership).where(
            Membership.principal_id == principal_id,
            Membership.workspace_id == workspace_id,
        )
    )
    if membership is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no workspace membership")
    principal = principal or await db.get(Principal, principal_id)
    if principal is None or not principal.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "inactive principal")
    if payload.get("sub") != principal.subject:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token subject")
    roles = _membership_roles(membership.roles)
    groups = _membership_groups(membership.group_ids)
    fingerprint = "|".join(sorted([*(r.value for r in roles), *groups]))
    return AuthContext(
        principal_id=principal_id,
        workspace_id=workspace_id,
        subject=principal.subject,
        email=principal.email,
        display_name=principal.display_name,
        roles=roles,
        group_ids=groups,
        permission_fingerprint=fingerprint,
    )


def require(capability: str):
    async def _inner(auth: AuthContext = Depends(get_auth)) -> AuthContext:
        if not auth.can(capability):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"missing capability {capability}")
        return auth

    return _inner
