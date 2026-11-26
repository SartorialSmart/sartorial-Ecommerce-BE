from __future__ import annotations

from typing import Any

from django.http import HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import IsAdminOrSellerRole
from apps.common.audit import record_audit
from apps.common.models import AuditLog
from apps.orders.models import Order
from apps.tenants.admin_mixins import TenantScopedAdminMixin
from apps.tenants.services import assert_tenant_writable

from . import services
from .models import Invoice
from .serializers import (
    InvoiceCreateSerializer,
    InvoiceSerializer,
    InvoiceUpdateSerializer,
    SendInvoiceSerializer,
)


class InvoiceAdminViewSet(
    TenantScopedAdminMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet[Invoice],
):
    permission_classes = [IsAdminOrSellerRole]
    queryset = Invoice.objects.select_related("order", "tenant").prefetch_related("order__lines")
    serializer_class = InvoiceSerializer
    filterset_fields = ["status"]
    search_fields = ["number", "customer_name", "customer_email", "order__number"]

    def get_serializer_class(self) -> Any:
        if self.action in {"update", "partial_update"}:
            return InvoiceUpdateSerializer
        if self.action == "send":
            return SendInvoiceSerializer
        return InvoiceSerializer

    @extend_schema(request=InvoiceCreateSerializer, responses={201: InvoiceSerializer})
    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = InvoiceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        order = Order.objects.select_related("tenant").filter(id=data["order"]).first()
        if order is None:
            return Response({"order": ["Order not found."]}, status=status.HTTP_404_NOT_FOUND)
        assert_tenant_writable(request, order.tenant)
        invoice = services.create_invoice(
            order=order,
            actor=request.user,
            customer_name=data["customer_name"],
            customer_email=data["customer_email"],
            customer_logo_url=data["customer_logo_url"],
            notes=data["notes"],
            due_date=data["due_date"],
        )
        return Response(InvoiceSerializer(invoice).data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer: Any) -> None:
        invoice = serializer.instance
        assert_tenant_writable(self.request, invoice.tenant)
        before = {field: getattr(invoice, field) for field in serializer.validated_data}
        updated = serializer.save()
        record_audit(
            actor=self.request.user,
            action=AuditLog.Action.UPDATE,
            target_type="invoices.Invoice",
            target_id=str(updated.id),
            changes={
                field: {"before": str(value), "after": str(getattr(updated, field))}
                for field, value in before.items()
            },
        )

    @extend_schema(responses={200: bytes}, tags=["invoices-admin"])
    @action(detail=True, methods=["get"])
    def pdf(self, request: Request, pk: str | None = None) -> HttpResponse:
        invoice = self.get_object()
        content = services.build_invoice_pdf(invoice)
        response = HttpResponse(content, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{invoice.number}.pdf"'
        return response

    @extend_schema(request=SendInvoiceSerializer, responses={200: dict}, tags=["invoices-admin"])
    @action(detail=True, methods=["post"])
    def send(self, request: Request, pk: str | None = None) -> Response:
        invoice = self.get_object()
        serializer = SendInvoiceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        recipient = data["to"].strip() or invoice.customer_email
        if not recipient:
            return Response({"to": ["A recipient email is required."]}, status=400)
        try:
            response = services.send_invoice(
                invoice=invoice,
                to=recipient,
                subject=data["subject"],
                message=data["message"],
            )
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        record_audit(
            actor=request.user,
            action=AuditLog.Action.UPDATE,
            target_type="invoices.Invoice",
            target_id=str(invoice.id),
            changes={"status": {"before": "draft", "after": "sent"}},
            metadata={"to": recipient, "provider": response.get("backend", "email")},
        )
        return Response({"delivered": True, "to": recipient, "provider": response})
