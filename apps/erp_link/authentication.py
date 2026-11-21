"""DRF authentication for machine-to-machine ERP publication calls.

Consumes the per-tenant ``TenantApiKey`` (raw keys look like ``sk_…``; only a
SHA-256 hash is stored). Send the key either as ``Authorization: Bearer sk_…``
or as ``X-Api-Key: sk_…``. The tenant is always taken from the key, never from
the request body or headers beyond that.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest
from rest_framework import authentication, exceptions

from apps.tenants import services as tenant_services
from apps.tenants.models import TenantApiKey


class ServicePrincipal:
    """Authenticated principal for M2M calls (not a real account)."""

    is_active = True
    is_authenticated = True
    is_anonymous = False
    role = "service"
    pk = None
    id = None

    def __init__(self, key: TenantApiKey) -> None:
        self.api_key = key
        self.tenant = key.tenant

    def __str__(self) -> str:
        return f"service:{self.tenant.slug}:{self.api_key.name}"


def _extract_raw_key(request: HttpRequest) -> str:
    header = request.headers.get("Authorization", "").strip()
    if header.startswith("Bearer "):
        candidate = header[len("Bearer ") :].strip()
        if candidate.startswith("sk_"):
            return candidate
    header_key = request.headers.get("X-Api-Key", "").strip()
    if header_key.startswith("sk_"):
        return header_key
    return ""


class TenantApiKeyAuthentication(authentication.BaseAuthentication):
    """Authenticate a per-tenant service key; bind ``request.tenant`` to it."""

    keyword = "Bearer"

    def authenticate(self, request: Any) -> tuple[ServicePrincipal, TenantApiKey] | None:
        raw = _extract_raw_key(request)
        if not raw:
            # No sk_ credential presented — let other authenticators (JWT/session)
            # try. Never guess.
            return None
        key = tenant_services.authenticate_service_key(raw)
        if key is None:
            raise exceptions.AuthenticationFailed("Invalid or inactive service key.")
        # The key is authoritative for tenancy: pin request.tenant to the key's
        # store so downstream scoping can never honour a foreign store slug.
        request.tenant = key.tenant
        request.erp_api_key = key
        return ServicePrincipal(key), key

    def authenticate_header(self, request: Any) -> str:
        return self.keyword
