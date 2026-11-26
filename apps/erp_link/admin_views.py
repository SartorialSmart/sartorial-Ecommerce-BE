from __future__ import annotations

from typing import Any

from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import status, views
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import IsAdminOrSellerRole
from apps.common.audit import record_audit
from apps.common.models import AuditLog
from apps.tenants.models import Tenant, TenantApiKey, TenantType
from apps.tenants.services import issue_api_key, resolve_write_tenant

from .admin_serializers import LinkErpSerializer

KEY_NAME = "ERP self-link"


def _tenant(request: Request) -> Tenant:
    tenant = resolve_write_tenant(request)
    if tenant is None:
        raise ValidationError("Pass X-Tenant-Slug to choose the store to link.")
    return tenant


def _active_keys(tenant: Tenant) -> Any:
    return TenantApiKey.objects.filter(tenant=tenant, name=KEY_NAME, is_active=True).order_by(
        "-created_at"
    )


def _status(tenant: Tenant) -> dict[str, Any]:
    key = _active_keys(tenant).first()
    linked = tenant.type == TenantType.ERP_SUBSCRIBER and bool(tenant.erp_business_id)
    return {
        "tenant": tenant.slug,
        "linked": linked,
        "erp_business_id": tenant.erp_business_id or "",
        "tenant_type": tenant.type,
        "api_key_prefix": key.prefix if key else "",
        "api_key_created_at": key.created_at if key else None,
        "api_key_last_used_at": key.last_used_at if key else None,
        "sync_endpoints": {
            "catalog": "/api/v1/erp/catalog/sync/",
            "inventory": "/api/v1/erp/inventory/",
        },
    }


class SellerErpLinkView(views.APIView):
    permission_classes = [IsAdminOrSellerRole]

    @extend_schema(responses={200: dict}, tags=["erp-link-admin"])
    def get(self, request: Request) -> Response:
        return Response(_status(_tenant(request)))

    @extend_schema(request=LinkErpSerializer, responses={200: dict}, tags=["erp-link-admin"])
    def post(self, request: Request) -> Response:
        tenant = _tenant(request)
        serializer = LinkErpSerializer(data=request.data, context={"tenant": tenant})
        serializer.is_valid(raise_exception=True)
        erp_business_id = serializer.validated_data["erp_business_id"]
        before_type = tenant.type
        with transaction.atomic():
            tenant.type = TenantType.ERP_SUBSCRIBER
            tenant.erp_business_id = erp_business_id
            tenant.save(update_fields=["type", "erp_business_id", "updated_at"])
            key = _active_keys(tenant).first()
            raw_key = ""
            if key is None:
                key, raw_key = issue_api_key(tenant=tenant, name=KEY_NAME)
            record_audit(
                actor=request.user,
                action=AuditLog.Action.UPDATE,
                target_type="tenants.Tenant",
                target_id=str(tenant.id),
                changes={
                    "type": {"before": before_type, "after": tenant.type},
                    "erp_business_id": {"before": "", "after": erp_business_id},
                },
                metadata={"self_link": True},
            )
        payload = _status(tenant)
        if raw_key:
            payload["api_key"] = raw_key
        return Response(payload, status=status.HTTP_200_OK)

    @extend_schema(responses={200: dict}, tags=["erp-link-admin"])
    def delete(self, request: Request) -> Response:
        tenant = _tenant(request)
        previous = tenant.erp_business_id or ""
        with transaction.atomic():
            tenant.type = TenantType.INDEPENDENT
            tenant.erp_business_id = None
            tenant.save(update_fields=["type", "erp_business_id", "updated_at"])
            _active_keys(tenant).update(is_active=False)
            record_audit(
                actor=request.user,
                action=AuditLog.Action.UPDATE,
                target_type="tenants.Tenant",
                target_id=str(tenant.id),
                changes={
                    "type": {"before": TenantType.ERP_SUBSCRIBER, "after": tenant.type},
                    "erp_business_id": {"before": previous, "after": ""},
                },
                metadata={"self_unlink": True},
            )
        return Response(_status(tenant))


class SellerErpKeyView(views.APIView):
    permission_classes = [IsAdminOrSellerRole]

    @extend_schema(responses={200: dict}, tags=["erp-link-admin"])
    def post(self, request: Request) -> Response:
        tenant = _tenant(request)
        if tenant.type != TenantType.ERP_SUBSCRIBER or not tenant.erp_business_id:
            raise ValidationError("Link an ERP account before generating a sync key.")
        with transaction.atomic():
            _active_keys(tenant).update(is_active=False)
            key, raw_key = issue_api_key(tenant=tenant, name=KEY_NAME)
            record_audit(
                actor=request.user,
                action=AuditLog.Action.CREATE,
                target_type="tenants.TenantApiKey",
                target_id=str(key.id),
                changes={"api_key": {"before": "", "after": key.prefix}},
                metadata={"regenerated": True},
            )
        payload = _status(tenant)
        payload["api_key"] = raw_key
        return Response(payload, status=status.HTTP_200_OK)
