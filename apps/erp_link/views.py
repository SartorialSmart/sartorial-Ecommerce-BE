"""Inbound ERP publication API (service-key authenticated).

The ERP authenticates with its per-tenant ``sk_…`` key; the tenant is taken
from the key, never from the payload. All endpoints are one-way (ERP →
marketplace): the marketplace never edits ERP-owned records outside this API.
"""

from __future__ import annotations

import logging

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .authentication import TenantApiKeyAuthentication
from .permissions import IsErpSubscriberTenant
from .serializers import ErpProductSyncSerializer, ErpStockSyncSerializer

logger = logging.getLogger(__name__)


class _ErpApiView(APIView):
    authentication_classes = [TenantApiKeyAuthentication]
    permission_classes = [IsErpSubscriberTenant]


class ProductSyncView(_ErpApiView):
    """Upsert one ERP product (with variants) into the calling store."""

    serializer_class = ErpProductSyncSerializer

    @extend_schema(
        tags=["ERP integration"],
        summary="Upsert an ERP product and its variants",
        request=ErpProductSyncSerializer,
    )
    def post(self, request: Request) -> Response:
        serializer = ErpProductSyncSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = services.upsert_product(tenant=request.tenant, payload=serializer.validated_data)
        code = status.HTTP_201_CREATED if result["created"] else status.HTTP_200_OK
        return Response(result, status=code)


class StockSyncView(_ErpApiView):
    """Set on-hand stock for ERP-linked variants (source of truth: ERP)."""

    serializer_class = ErpStockSyncSerializer

    @extend_schema(
        tags=["ERP integration"],
        summary="Set on-hand stock for one or more SKUs",
        request=ErpStockSyncSerializer,
    )
    def post(self, request: Request) -> Response:
        serializer = ErpStockSyncSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = services.set_stock_levels(
            tenant=request.tenant, items=serializer.validated_data["items"]
        )
        return Response(result, status=status.HTTP_200_OK)

    @extend_schema(tags=["ERP integration"], summary="Current stock snapshot (for reconciliation)")
    def get(self, request: Request) -> Response:
        return Response({"inventory": services.stock_snapshot(tenant=request.tenant)})
