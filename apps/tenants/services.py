"""Tenant service layer: provisioning, membership, service-key auth."""

from __future__ import annotations

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
