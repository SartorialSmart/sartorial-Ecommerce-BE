"""Multi-tenant foundation for SartorialEcommerce.

Tenancy model (confirmed): **isolated stores per tenant** on a **shared
database** scoped by ``tenant_id``.

* Each tenant is one isolated store: either an ERP subscriber's store
  (``type=erp_subscriber``, linked via ``erp_business_id`` — the ERP is the
  source of truth for its products/prices/stock) or an independent seller's
  store (``type=independent``, managed natively in this backend).
* Phase 1 ships the tenant registry, membership, service API keys, request
  resolution middleware and the ``TenantScopedModel`` mixin. Phase 3 attaches
  ``tenant`` FKs to catalogue/orders/inventory/promotions and enforces
  isolation in the service layer (see ``docs`` in this module docstring flow).

Resolution order (middleware): ``X-Tenant-Slug`` header > ``?tenant=`` query
param > ``TENANT_SLUG`` setting fallback > host-subdomain match on
``Tenant.domain``. Unresolved requests get ``request.tenant = None`` and
public catalogue endpoints fall back to the default tenant where configured.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel, SoftDeleteModel, TimeStampedModel


class TenantType(models.TextChoices):
    ERP_SUBSCRIBER = "erp_subscriber", "ERP subscriber"
    INDEPENDENT = "independent", "Independent seller"


class TenantStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"


class MembershipRole(models.TextChoices):
    OWNER = "owner", "Owner"
    MANAGER = "manager", "Manager"
    STAFF = "staff", "Staff"


class Tenant(BaseModel, SoftDeleteModel):
    """One isolated store."""

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=80, unique=True, db_index=True)
    type = models.CharField(
        max_length=20, choices=TenantType.choices, default=TenantType.INDEPENDENT, db_index=True
    )
    status = models.CharField(
        max_length=20, choices=TenantStatus.choices, default=TenantStatus.ACTIVE, db_index=True
    )
    # Link to the Sartorial ERP business that owns this store (Phase 4).
    # Null for independent sellers. Unique when set so one ERP business maps
    # to exactly one tenant.
    erp_business_id = models.CharField(
        max_length=80, null=True, blank=True, unique=True, db_index=True
    )
    # Optional custom storefront domain (e.g. shop.example.com).
    domain = models.CharField(max_length=255, null=True, blank=True, unique=True)
    logo_url = models.URLField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="TenantMembership", related_name="tenants"
    )

    class Meta:
        ordering = ("name",)
        indexes = [
            models.Index(fields=["type", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} <{self.slug}>"

    @property
    def is_erp_managed(self) -> bool:
        return self.type == TenantType.ERP_SUBSCRIBER

    @property
    def is_active(self) -> bool:
        return self.status == TenantStatus.ACTIVE


class TenantMembership(TimeStampedModel):
    """Links a user to a tenant with a store-level role."""

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tenant_memberships"
    )
    role = models.CharField(
        max_length=20, choices=MembershipRole.choices, default=MembershipRole.STAFF
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "user"], name="uniq_member_per_tenant"),
        ]
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.user} → {self.tenant.slug} ({self.role})"


class TenantApiKey(TimeStampedModel):
    """Service credential for machine-to-machine access (ERP publication link).

    Only a SHA-256 hash is stored. The raw key is shown once at creation and
    must be kept in the caller's vault (ERP side / per-tenant integration).
    """

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="api_keys")
    name = models.CharField(max_length=120, help_text="e.g. 'sartorial-erp-prod'")
    prefix = models.CharField(max_length=16, db_index=True)
    key_hash = models.CharField(max_length=64)
    is_active = models.BooleanField(default=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["tenant", "is_active"])]

    def __str__(self) -> str:
        return f"{self.tenant.slug}:{self.name} ({self.prefix}…)"

    @staticmethod
    def hash_key(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def generate(cls, tenant: Tenant, name: str) -> tuple[TenantApiKey, str]:
        raw = f"sk_{secrets.token_urlsafe(32)}"
        prefix = raw[:10]
        obj = cls.objects.create(
            tenant=tenant, name=name, prefix=prefix, key_hash=cls.hash_key(raw)
        )
        return obj, raw

    def verify(self, raw: str) -> bool:
        return hmac.compare_digest(self.key_hash, self.hash_key(raw))


class TenantScopedQuerySet(models.QuerySet):
    def for_tenant(self, tenant: Tenant | None) -> TenantScopedQuerySet:
        if tenant is None:
            return self.none()
        return self.filter(tenant=tenant)


class TenantScopedManager(models.Manager):
    def get_queryset(self) -> TenantScopedQuerySet:
        return TenantScopedQuerySet(self.model, using=self._db)

    def for_tenant(self, tenant: Tenant | None) -> TenantScopedQuerySet:
        return self.get_queryset().for_tenant(tenant)


class TenantScopedModel(models.Model):
    """Mixin for Phase 3: attach ``tenant`` to domain models.

    Usage: ``class Product(TenantScopedModel, BaseModel): ...`` with
    ``objects = TenantScopedManager()``. All service-layer reads must go
    through ``.for_tenant(request.tenant)``; admin/platform views bypass via
    ``all_objects`` or explicit tenant filter.
    """

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="%(class)s_set")

    objects = TenantScopedManager()

    class Meta:
        abstract = True
