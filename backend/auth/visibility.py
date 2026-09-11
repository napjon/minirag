from __future__ import annotations

from backend.auth.security import AuthContext
from backend.domain.enums import LifecycleStatus, Role, Visibility


def can_read_document(
    auth: AuthContext,
    *,
    visibility: str,
    allowed_groups: list[str] | None,
    lifecycle_status: str = LifecycleStatus.PUBLISHED.value,
) -> bool:
    if lifecycle_status != LifecycleStatus.PUBLISHED.value:
        return Role.ADMIN in auth.roles or Role.REVIEWER in auth.roles
    if Role.ADMIN in auth.roles or Role.REVIEWER in auth.roles:
        return True
    if visibility == Visibility.PUBLIC_WORKSPACE.value:
        return True
    if visibility == Visibility.RESTRICTED.value:
        return bool(set(allowed_groups or []) & set(auth.group_ids))
    if visibility == Visibility.REVIEWER_ONLY.value:
        return False
    return False


def can_read_product(
    auth: AuthContext, *, visibility: str, allowed_groups: list[str] | None = None
) -> bool:
    return can_read_document(
        auth,
        visibility=visibility or Visibility.PUBLIC_WORKSPACE.value,
        allowed_groups=allowed_groups,
        lifecycle_status=LifecycleStatus.PUBLISHED.value,
    )
