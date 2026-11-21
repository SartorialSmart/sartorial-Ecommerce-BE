"""Tenant service layer: provisioning, membership, service-key auth."""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import MembershipRole, Tenant, TenantApiKey, TenantMembership, TenantStatus, TenantType

User = get_user_model()


def create_tenant(
    *,
    name: str,
    slug: str,
    type: str = TenantType.INDEPENDENT,
    erp_business_id: str | None = None,
    domain: str | None = None,
    owner_email: str | None = None,
) -> Tenant:
    slug = slug.strip().lower()
    tenant = Tenant.objects.create(
        name=name.strip(),
        slug=slug,
        type=type,
        status=TenantStatus.ACTIVE,
        erp_business_id=erp_business_id,
        domain=domain,
    )
    if owner_email:
        try:
            user = User.objects.get(email__iexact=owner_email.strip())
        except User.DoesNotExist:
            user = None
        if user is not None:
            TenantMembership.objects.get_or_create(
                tenant=tenant, user=user, defaults={"role": MembershipRole.OWNER}
            )
    return tenant


def add_member(*, tenant: Tenant, email: str, role: str = MembershipRole.STAFF) -> TenantMembership:
    user = User.objects.get(email__iexact=email.strip())
    membership, created = TenantMembership.objects.get_or_create(
        tenant=tenant, user=user, defaults={"role": role}
    )
    if not created and membership.role != role:
        membership.role = role
        membership.save(update_fields=["role", "updated_at"])
    return membership


def issue_api_key(*, tenant: Tenant, name: str) -> tuple[TenantApiKey, str]:
    return TenantApiKey.generate(tenant, name)


def authenticate_service_key(raw: str) -> TenantApiKey | None:
    """Validate a raw service key, returning the key row (with tenant)."""
    if not raw or not raw.startswith("sk_"):
        return None
    prefix = raw[:10]
    candidates = TenantApiKey.objects.filter(prefix=prefix, is_active=True).select_related("tenant")
    for candidate in candidates:
        if candidate.verify(raw) and candidate.tenant.is_active:
            candidate.last_used_at = timezone.now()
            candidate.save(update_fields=["last_used_at"])
            return candidate
    return None


def get_or_create_default_tenant() -> Tenant:
    """Idempotent bootstrap: the single-store default for pre-multitenant data."""
    from config.branding import DEFAULT_STORE_NAME

    tenant, _ = Tenant.objects.get_or_create(
        slug="default",
        defaults={"name": DEFAULT_STORE_NAME, "type": TenantType.INDEPENDENT},
    )
    return tenant


def get_effective_tenant(request: Any | None) -> Tenant | None:
    """Tenant to scope a request to. Read-path safe (never writes).

    ``request.tenant`` (middleware) wins; otherwise the ``default`` tenant when
    it exists (pre-multitenant data, tests, storeless browsing); else None,
    in which case callers see legacy unscoped (``tenant NULL``) rows only —
    never another store's data.
    """
    tenant = getattr(request, "tenant", None) if request is not None else None
    if tenant is not None:
        return tenant
    return Tenant.objects.filter(slug="default").first()


def resolve_write_tenant(request: Any) -> Tenant | None:
    """Tenant a write should target, enforcing store membership.

    Platform admins keep legacy behaviour: the request-resolved tenant, or
    ``None`` (callers backfill the ``default`` store). Sellers must target a
    store they belong to: the request-resolved tenant when set, otherwise their
    only store. Raises a DRF ``PermissionDenied`` (403) or ``ValidationError``
    (400) instead of falling back, so a seller can never write into — or be
    silently assigned — a store they don't own.
    """
    from rest_framework.exceptions import PermissionDenied, ValidationError

    user = getattr(request, "user", None)
    requested = getattr(request, "tenant", None)
    if requested is None:
        params = getattr(request, "query_params", {}) or {}
        data = getattr(request, "data", {})
        slug = (
            params.get("tenant")
            or (data.get("tenant") if hasattr(data, "get") else None)
            or (data.get("tenant_slug") if hasattr(data, "get") else None)
        )
        if slug:
            requested = Tenant.objects.filter(slug=str(slug).strip().lower()).first()
    if getattr(user, "role", None) == "admin":
        return requested
    if not (user and getattr(user, "is_authenticated", False)):
        raise PermissionDenied("Authentication required.")
    memberships = list(user.tenants.all())
    if requested is not None:
        if any(member.id == requested.id for member in memberships):
            return requested
        raise PermissionDenied("You are not a member of that store.")
    if len(memberships) == 1:
        return memberships[0]
    if not memberships:
        raise PermissionDenied("Your account is not linked to a store yet.")
    raise ValidationError("This account manages multiple stores; pass X-Tenant-Slug.")


def assert_tenant_writable(request: Any, tenant: Any | None) -> None:
    """Raise unless the requester may write to ``tenant``.

    Platform admins may write anywhere. Everyone else must belong to the
    store; a NULL-tenant (legacy/global) record is admin-only. No-op when
    there is no request (internal/service-layer calls) — the HTTP permission
    layer has already gated those paths.
    """
    from rest_framework.exceptions import PermissionDenied

    if request is None:
        return
    user = getattr(request, "user", None)
    if getattr(user, "role", None) == "admin":
        return
    tenant_id = getattr(tenant, "id", tenant)
    memberships = getattr(user, "tenants", None) if user is not None else None
    if (
        tenant_id is not None
        and memberships is not None
        and memberships.filter(id=tenant_id).exists()
    ):
        return
    raise PermissionDenied("You are not a member of that store.")


def tenant_filter(tenant: Any | None, path: str = "tenant") -> dict[str, Any]:
    """ORM filter scoping a queryset to one store.

    A resolved tenant filters to its rows; ``None`` restricts to legacy
    unscoped rows so an unknown store never sees another store's catalogue.
    """
    if tenant is None:
        return {f"{path}__isnull": True}
    return {path: getattr(tenant, "id", tenant)}
