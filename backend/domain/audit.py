from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.security import AuthContext
from backend.domain.models import AuditEvent, Interaction


def record_interaction(
    db: AsyncSession,
    auth: AuthContext,
    *,
    request_id: str,
    capability: str,
    status: str,
    request: dict[str, Any],
    response: dict[str, Any] | list | None = None,
    evidence: list | None = None,
    manifest: dict[str, Any] | None = None,
    final_state: str = "completed",
    cost_usd: Decimal | float | str = Decimal("0"),
) -> Interaction:
    effective_manifest = {"permission_fingerprint": auth.permission_fingerprint, **(manifest or {})}
    row = Interaction(
        workspace_id=auth.workspace_id,
        principal_id=auth.principal_id,
        request_id=request_id,
        capability=capability,
        status=status,
        request=request,
        response=response if response is not None else {},
        evidence=evidence or [],
        execution_manifest=effective_manifest,
        cost_usd=Decimal(str(cost_usd)),
        final_state=final_state,
    )
    db.add(row)
    # Keep a compact, append-only audit trail alongside the detailed interaction
    # payload. The interaction stores the full redacted request/response; the
    # audit row is intentionally small enough for long-term retention and export.
    db.add(
        AuditEvent(
            workspace_id=auth.workspace_id,
            principal_id=auth.principal_id,
            action="interaction.failed" if final_state == "failed" else "interaction.completed",
            resource_type="interaction",
            resource_id=request_id,
            details={
                "capability": capability,
                "status": status,
                "final_state": final_state,
                "permission_fingerprint": auth.permission_fingerprint,
            },
            authorized=True,
        )
    )
    return row


def record_audit_event(
    db: AsyncSession,
    auth: AuthContext,
    *,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict[str, Any] | None = None,
    authorized: bool = True,
) -> AuditEvent:
    """Append a consequential state-change or authorization audit event."""
    row = AuditEvent(
        workspace_id=auth.workspace_id,
        principal_id=auth.principal_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details or {},
        authorized=authorized,
    )
    db.add(row)
    return row
