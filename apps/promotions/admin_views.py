"""Admin coupon management (role: admin or store seller)."""

from __future__ import annotations

from rest_framework import serializers

from apps.accounts.permissions import IsAdminOrSellerRole
from apps.common.audit_mixins import AuditedModelViewSet
from apps.tenants.admin_mixins import TenantScopedAdminMixin
from apps.tenants.services import assert_tenant_writable, resolve_write_tenant

from .models import Coupon


class CouponAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Coupon
        fields = (
            "id",
            "code",
            "description",
            "discount_type",
            "value",
            "is_active",
            "valid_from",
            "valid_until",
            "min_spend",
            "category",
            "first_order_only",
            "stackable",
            "max_uses",
            "used_count",
        )
        read_only_fields = ("used_count",)

    def validate_category(self, value):  # type: ignore[no-untyped-def]
        if value is None:
            return value
        request = self.context.get("request")
        if getattr(getattr(request, "user", None), "role", None) == "admin":
            return value
        assert_tenant_writable(request, getattr(value, "tenant", None))
        return value


class CouponAdminViewSet(TenantScopedAdminMixin, AuditedModelViewSet):
    permission_classes = [IsAdminOrSellerRole]
    queryset = Coupon.objects.all()
    serializer_class = CouponAdminSerializer
    filterset_fields = ["is_active", "discount_type"]
    search_fields = ["code", "description"]

    def perform_create(self, serializer) -> None:  # type: ignore[no-untyped-def]
        tenant = resolve_write_tenant(self.request)
        if tenant is None:
            super().perform_create(serializer)
            return
        assert_tenant_writable(self.request, tenant)
        serializer.save(tenant=tenant)
