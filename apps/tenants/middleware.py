"""Resolve the current tenant for each request.

Order: ``X-Tenant-Slug`` header > ``?tenant=`` query param > host match on
``Tenant.domain`` > ``settings.TENANT_SLUG`` fallback. Sets
``request.tenant`` (None when unresolved). Never 4xx on its own — views decide
whether a tenant is required.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.utils.deprecation import MiddlewareMixin

from .models import Tenant, TenantStatus


def resolve_tenant(*, slug: str | None = None, host: str | None = None) -> Tenant | None:
    if slug:
        try:
            return Tenant.objects.get(slug=slug.strip().lower(), status=TenantStatus.ACTIVE)
        except Tenant.DoesNotExist:
            return None
    if host:
        host = host.split(":")[0].lower()
        try:
            return Tenant.objects.get(domain__iexact=host, status=TenantStatus.ACTIVE)
        except Tenant.DoesNotExist:
            return None
    return None


class TenantMiddleware(MiddlewareMixin):
    def process_request(self, request: Any) -> None:
        slug = request.headers.get("X-Tenant-Slug") or request.GET.get("tenant")
        tenant = resolve_tenant(slug=slug) if slug else None
        if tenant is None:
            host = request.get_host() if hasattr(request, "get_host") else None
            tenant = resolve_tenant(host=host) if host else None
        if tenant is None:
            fallback = getattr(settings, "TENANT_SLUG", "") or ""
            tenant = resolve_tenant(slug=fallback) if fallback else None
        request.tenant = tenant
