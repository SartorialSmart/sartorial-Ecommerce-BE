"""Tenant-aware DRF permissions."""

from __future__ import annotations

from typing import Any

from rest_framework.permissions import BasePermission
from rest_framework.request import Request


class IsPlatformAdmin(BasePermission):
    def has_permission(self, request: Request, view: Any) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and getattr(user, "role", "") == "admin")


class IsTenantMember(BasePermission):
    """Request has a resolved tenant and the user belongs to it (or is platform admin)."""

    def has_permission(self, request: Request, view: Any) -> bool:
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if getattr(user, "role", "") == "admin":
            return True
        tenant = getattr(request, "tenant", None)
        if tenant is None:
            return False
        return tenant.memberships.filter(user=user).exists()


class IsTenantOwner(BasePermission):
    def has_permission(self, request: Request, view: Any) -> bool:
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if getattr(user, "role", "") == "admin":
            return True
        tenant = getattr(request, "tenant", None)
        if tenant is None:
            return False
        return tenant.memberships.filter(user=user, role="owner").exists()
