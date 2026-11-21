"""Permissions for the ERP publication API."""

from __future__ import annotations

from typing import Any

from rest_framework import permissions

from apps.tenants.models import TenantType


class IsErpSubscriberTenant(permissions.BasePermission):
    """Only active ``erp_subscriber`` stores may call the publication API.

    Independent sellers manage their catalogue natively through the seller
    admin API; letting an ERP key write into their store would break the
    source-of-truth rule (marketplace owns independent catalogues).
    """

    message = "This endpoint is only available to ERP-linked stores (type=erp_subscriber)."

    def has_permission(self, request: Any, view: Any) -> bool:
        key = getattr(request, "erp_api_key", None)
        tenant = getattr(request, "tenant", None)
        if key is None or tenant is None:
            return False
        return bool(key.is_active and tenant.is_active and tenant.type == TenantType.ERP_SUBSCRIBER)
