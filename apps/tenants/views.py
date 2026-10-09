"""Public tenant endpoints (storefront discovery)."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .models import Tenant, TenantStatus
from .serializers import TenantPublicSerializer


class TenantLookupView(generics.GenericAPIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = TenantPublicSerializer

    @extend_schema(summary="Resolve a store by slug or domain", tags=["tenants"])
    def get(self, request) -> Response:
        slug = request.query_params.get("slug") or getattr(request.tenant, "slug", None)
        tenant = getattr(request, "tenant", None)
        if tenant is None and slug:
            tenant = Tenant.objects.filter(slug=slug, status=TenantStatus.ACTIVE).first()
        if tenant is None:
            return Response({"detail": "Store not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(TenantPublicSerializer(tenant).data)


class TenantListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = TenantPublicSerializer

    @extend_schema(summary="List active storefronts", tags=["tenants"])
    def get_queryset(self):  # type: ignore[override]
        return Tenant.objects.filter(status=TenantStatus.ACTIVE).order_by("name")[:100]
