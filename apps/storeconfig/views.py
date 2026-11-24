"""Thin views for store configuration.

A public read endpoint exposes only storefront-safe keys; full admin management
(all keys, writes) is role-gated under ``/api/v1/admin/storeconfig/``. Writes go
through the service layer, which validates and audit-logs each change.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import status, views
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import IsAdminOrSellerRole

from . import selectors, services
from .schema import PUBLIC_KEYS, SETTINGS
from .serializers import (
    BulkSettingsWriteSerializer,
    SettingSpecSerializer,
    SettingWriteSerializer,
)


def _current_tenant(request: Request):
    from apps.tenants.services import get_effective_tenant

    return get_effective_tenant(request)


class PublicConfigView(views.APIView):
    """GET storefront-safe settings as a flat ``{key: value}`` map."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    @extend_schema(responses={200: dict}, tags=["storeconfig"])
    def get(self, request: Request) -> Response:
        tenant = _current_tenant(request)
        values = selectors.get_all_settings(tenant)
        public = {k: v for k, v in values.items() if k in PUBLIC_KEYS}
        return Response({"settings": public, "tenant": getattr(tenant, "slug", None)})


def _spec_dict(spec, values: dict) -> dict:
    stored = values.get(spec.key, spec.default)
    item = {
        "key": spec.key,
        "section": spec.section,
        "type": spec.type,
        "description": spec.description,
        "default": "" if spec.secret else spec.default,
        "secret": spec.secret,
    }
    if spec.secret:
        # Never return a secret value — only whether one is set.
        item["value"] = ""
        item["is_set"] = bool(stored)
    else:
        item["value"] = stored
    return item


def _spec_payload(tenant=None) -> list[dict]:
    values = selectors.get_all_settings(tenant)
    return [_spec_dict(spec, values) for spec in SETTINGS.values()]


class AdminSettingsView(views.APIView):
    """List every setting spec, or bulk-update values for a store."""

    permission_classes = [IsAdminOrSellerRole]

    @extend_schema(responses={200: SettingSpecSerializer(many=True)}, tags=["storeconfig-admin"])
    def get(self, request: Request) -> Response:
        from apps.tenants.services import resolve_write_tenant

        tenant = resolve_write_tenant(request)
        return Response(
            {"settings": _spec_payload(tenant), "tenant": getattr(tenant, "slug", None)}
        )

    @extend_schema(
        request=BulkSettingsWriteSerializer, responses={200: dict}, tags=["storeconfig-admin"]
    )
    def patch(self, request: Request) -> Response:
        from apps.tenants.services import resolve_write_tenant

        tenant = resolve_write_tenant(request)
        serializer = BulkSettingsWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.set_many(serializer.validated_data["values"], actor=request.user, tenant=tenant)
        return Response(
            {"settings": _spec_payload(tenant), "tenant": getattr(tenant, "slug", None)}
        )


class AdminSettingDetailView(views.APIView):
    """Read/update/reset a single setting by key."""

    permission_classes = [IsAdminOrSellerRole]

    @extend_schema(
        request=SettingWriteSerializer,
        responses={200: SettingSpecSerializer},
        tags=["storeconfig-admin"],
    )
    def put(self, request: Request, key: str) -> Response:
        from apps.tenants.services import resolve_write_tenant

        if key not in SETTINGS:
            return Response(status=status.HTTP_404_NOT_FOUND)
        tenant = resolve_write_tenant(request)
        serializer = SettingWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.set_setting(
            key, serializer.validated_data["value"], actor=request.user, tenant=tenant
        )
        return Response(_single_payload(key, tenant))

    @extend_schema(responses={204: None}, tags=["storeconfig-admin"])
    def delete(self, request: Request, key: str) -> Response:
        from apps.tenants.services import resolve_write_tenant

        if key not in SETTINGS:
            return Response(status=status.HTTP_404_NOT_FOUND)
        tenant = resolve_write_tenant(request)
        services.reset_setting(key, actor=request.user, tenant=tenant)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _single_payload(key: str, tenant=None) -> dict:
    spec = SETTINGS[key]
    return _spec_dict(spec, {key: selectors.get_setting(key, tenant=tenant)})
