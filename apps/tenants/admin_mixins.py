"""Reusable admin scoping for tenant-owned resources.

v1 behaviour (platform-admin-only admin API; seller dashboard lands later):

* ``?tenant=<slug>`` filters the list to one store (all models via
  ``tenant_filter`` path, defaulting to a direct ``tenant`` FK).
* Creates honour the request's tenant (``X-Tenant-Slug`` header or ``?tenant=``
  override); otherwise the model's ``save()`` backfills the default store.
* Platform admins keep full cross-store access; non-admin sellers (when granted
  admin access) are restricted to their own store(s).
"""

from __future__ import annotations

from typing import Any


class TenantScopedAdminMixin:
    """Filter + assign by tenant. Expects a DRF ``ModelViewSet`` subclass."""

    # Lookup path to the tenant FK, e.g. "product__tenant" for Variant.
    tenant_filter: str = "tenant"
    # Models that must never auto-assign (NULL = meaningful, e.g. global Setting).
    tenant_auto_assign: bool = True

    def _requested_tenant(self) -> Any | None:
        from .models import Tenant

        header_tenant = getattr(self.request, "tenant", None)
        if header_tenant is not None:
            return header_tenant
        params = getattr(self.request, "query_params", {}) or {}
        data = getattr(self.request, "data", {}) or {}
        slug = params.get("tenant") or (data.get("tenant_slug") if hasattr(data, "get") else None)
        if slug:
            return Tenant.objects.filter(slug=str(slug).strip().lower()).first()
        return None

    def _seller_tenants(self) -> Any | None:
        """Tenant queryset restriction for non-platform-admin sellers, else None."""
        user = getattr(self.request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return None
        if getattr(user, "role", "") == "admin":
            return None
        return user.tenants.all()

    def get_queryset(self):  # type: ignore[no-untyped-def]
        qs = super().get_queryset()  # type: ignore[misc]
        seller_tenants = self._seller_tenants()
        if seller_tenants is not None:
            return qs.filter(**{f"{self.tenant_filter}__in": seller_tenants})
        requested = self._requested_tenant()
        if requested is not None:
            return qs.filter(**{self.tenant_filter: requested})
        return qs

    def perform_create(self, serializer) -> None:  # type: ignore[no-untyped-def]
        if not self.tenant_auto_assign:
            super().perform_create(serializer)  # type: ignore[misc]
            return
        model = getattr(getattr(self, "queryset", None), "model", None)
        has_tenant_field = model is not None and any(
            f.name == "tenant" for f in model._meta.get_fields()
        )
        if has_tenant_field and not serializer.validated_data.get("tenant"):
            requested = self._requested_tenant()
            if requested is not None:
                serializer.save(tenant=requested)
                return
        super().perform_create(serializer)  # type: ignore[misc]
