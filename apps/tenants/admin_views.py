"""Platform-admin tenant management + per-tenant member/key management.

Memberships are readable by the members themselves (sellers see their own
rows); inviting a member is open to platform admins and to the store's
owner/manager.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.permissions import IsAdminRole

from . import services
from .models import MembershipRole, Tenant, TenantApiKey, TenantMembership
from .permissions import IsPlatformAdmin
from .serializers import (
    TenantApiKeyCreateSerializer,
    TenantApiKeySerializer,
    TenantMembershipSerializer,
    TenantSerializer,
)

# Membership roles allowed to manage a store's members (besides platform admins).
_MEMBER_MANAGERS = (MembershipRole.OWNER, MembershipRole.MANAGER)


class TenantAdminViewSet(viewsets.ModelViewSet):
    queryset = Tenant.objects.all().order_by("name")
    serializer_class = TenantSerializer
    permission_classes = [IsAuthenticated, IsPlatformAdmin]
    lookup_field = "slug"
    filterset_fields = ("type", "status")
    search_fields = ("name", "slug", "erp_business_id", "domain")

    @extend_schema(summary="Add a member to this store")
    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated])
    def members(self, request, slug: str | None = None) -> Response:
        tenant = self.get_object()
        user = request.user
        if getattr(user, "role", "") != "admin":
            role = tenant.memberships.filter(user=user).values_list("role", flat=True).first()
            if role not in _MEMBER_MANAGERS:
                return Response(
                    {"detail": "Only the store owner or a manager can manage members."},
                    status=status.HTTP_403_FORBIDDEN,
                )
        email = str(request.data.get("email", "")).strip()
        role = str(request.data.get("role", "staff")).strip() or "staff"
        if not email:
            return Response({"email": ["Required."]}, status=status.HTTP_400_BAD_REQUEST)
        if role not in MembershipRole.values:
            return Response(
                {"role": ["Must be one of: owner, manager, staff."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            membership = services.add_member(tenant=tenant, email=email, role=role)
        except Exception:
            return Response({"email": ["User not found."]}, status=status.HTTP_404_NOT_FOUND)
        return Response(TenantMembershipSerializer(membership).data, status=201)

    @extend_schema(summary="Issue a service API key for this store (shown once)")
    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticated, IsPlatformAdmin])
    def keys(self, request, slug: str | None = None) -> Response:
        tenant = self.get_object()
        serializer = TenantApiKeyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        key_obj, raw = services.issue_api_key(
            tenant=tenant, name=str(serializer.validated_data["name"])
        )
        return Response(
            {**TenantApiKeySerializer(key_obj).data, "key": raw}, status=status.HTTP_201_CREATED
        )


class TenantMembershipAdminViewSet(viewsets.ReadOnlyModelViewSet):
    """Store members. Sellers read their own memberships; admins read all."""

    queryset = TenantMembership.objects.select_related("tenant", "user").all()
    serializer_class = TenantMembershipSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):  # type: ignore[override]
        if getattr(self, "swagger_fake_view", False):
            return TenantMembership.objects.none()
        qs = super().get_queryset()
        user = self.request.user
        if getattr(user, "role", "") != "admin":
            qs = qs.filter(user=user)
        tenant_slug = self.request.query_params.get("tenant")
        if tenant_slug:
            qs = qs.filter(tenant__slug=tenant_slug)
        return qs


class TenantApiKeyAdminViewSet(viewsets.ModelViewSet):
    queryset = TenantApiKey.objects.select_related("tenant").all()
    serializer_class = TenantApiKeySerializer
    permission_classes = [IsAuthenticated, IsAdminRole]
    http_method_names = ("get", "patch", "delete", "head", "options")

    def get_queryset(self):  # type: ignore[override]
        qs = super().get_queryset()
        tenant_slug = self.request.query_params.get("tenant")
        if tenant_slug:
            qs = qs.filter(tenant__slug=tenant_slug)
        return qs


class MyTenantsViewSet(viewsets.ReadOnlyModelViewSet):
    """Stores the requesting user belongs to (all stores for platform admins)."""

    serializer_class = TenantSerializer
    permission_classes = [IsAuthenticated]
    queryset = Tenant.objects.none()

    def get_queryset(self):  # type: ignore[override]
        if getattr(self, "swagger_fake_view", False):
            return Tenant.objects.none()
        user = self.request.user
        if getattr(user, "role", "") == "admin":
            return Tenant.objects.all().order_by("name")
        return Tenant.objects.filter(memberships__user=user).distinct().order_by("name")
