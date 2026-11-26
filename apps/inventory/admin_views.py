"""Admin inventory management (platform admins and store sellers)."""

from __future__ import annotations

from django.db.models import F
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdminOrSellerRole
from apps.catalog.models import Variant
from apps.common.audit import record_audit
from apps.common.audit_mixins import AuditedModelViewSet
from apps.common.models import AuditLog
from apps.tenants.admin_mixins import TenantScopedAdminMixin
from apps.tenants.services import assert_tenant_writable, resolve_write_tenant

from . import services
from .models import StockItem, Warehouse


class WarehouseAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        fields = ("id", "name", "code", "is_default", "is_active")


class WarehouseAdminViewSet(TenantScopedAdminMixin, AuditedModelViewSet):
    permission_classes = [IsAdminOrSellerRole]
    queryset = Warehouse.objects.all()
    serializer_class = WarehouseAdminSerializer


class StockItemSerializer(serializers.ModelSerializer):
    sku = serializers.CharField(source="variant.sku", read_only=True)
    warehouse_code = serializers.CharField(source="warehouse.code", read_only=True)
    available = serializers.IntegerField(read_only=True)

    class Meta:
        model = StockItem
        fields = (
            "id",
            "variant",
            "sku",
            "warehouse",
            "warehouse_code",
            "on_hand",
            "reserved",
            "available",
        )


class SetStockSerializer(serializers.Serializer):
    variant = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=0)
    warehouse_code = serializers.CharField(required=False, allow_blank=True)


class StockAdminView(APIView):
    """List stock items, or set a variant's on-hand quantity."""

    permission_classes = [IsAdminOrSellerRole]

    @extend_schema(responses={200: StockItemSerializer(many=True)}, tags=["inventory-admin"])
    def get(self, request: Request) -> Response:
        qs = StockItem.objects.select_related("variant", "warehouse")
        variant_id = request.query_params.get("variant")
        if variant_id:
            qs = qs.filter(variant_id=variant_id)
        search = request.query_params.get("search")
        if search:
            qs = qs.filter(variant__sku__icontains=search)
        if request.query_params.get("low_stock") in {"1", "true", "True"}:
            qs = qs.filter(on_hand__lte=F("reserved") + 5)
        if getattr(request.user, "role", None) == "admin":
            tenant = getattr(request, "tenant", None)
            if tenant is not None:
                qs = qs.filter(variant__product__tenant_id=tenant.id)
        else:
            tenant = resolve_write_tenant(request)
            if tenant is None:
                raise PermissionDenied("You are not a member of that store.")
            qs = qs.filter(variant__product__tenant_id=tenant.id)
        return Response(StockItemSerializer(qs, many=True).data)

    @extend_schema(
        request=SetStockSerializer, responses={200: StockItemSerializer}, tags=["inventory-admin"]
    )
    def post(self, request: Request) -> Response:
        serializer = SetStockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        write_tenant = resolve_write_tenant(request)
        variant = Variant.objects.filter(id=data["variant"]).first()
        if variant is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if write_tenant is not None and variant.product.tenant_id != write_tenant.id:
            raise PermissionDenied("You are not a member of that store.")
        assert_tenant_writable(request, variant.product.tenant_id)
        warehouse = None
        if data.get("warehouse_code"):
            warehouse = Warehouse.objects.filter(
                code=data["warehouse_code"], tenant_id=variant.product.tenant_id
            ).first()
        item = services.set_stock(variant, data["quantity"], warehouse=warehouse)
        record_audit(
            actor=request.user,
            action=AuditLog.Action.UPDATE,
            target_type="inventory.StockItem",
            target_id=str(item.id),
            changes={"on_hand": {"after": data["quantity"]}},
            metadata={"sku": variant.sku},
        )
        return Response(StockItemSerializer(item).data)
