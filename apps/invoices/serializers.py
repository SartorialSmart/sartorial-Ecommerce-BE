from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.orders.serializers import OrderLineSerializer

from .models import Invoice


class InvoiceSerializer(serializers.ModelSerializer[Invoice]):
    order_number = serializers.CharField(source="order.number", read_only=True)
    lines = serializers.SerializerMethodField()
    pdf_url = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = (
            "id",
            "number",
            "order",
            "order_number",
            "status",
            "customer_name",
            "customer_email",
            "customer_logo_url",
            "seller_name",
            "seller_email",
            "seller_logo_url",
            "currency",
            "subtotal",
            "discount",
            "total",
            "issue_date",
            "due_date",
            "notes",
            "last_sent_at",
            "send_error",
            "pdf_url",
            "lines",
            "created_at",
        )
        read_only_fields = fields

    def get_lines(self, obj: Invoice) -> Any:
        return OrderLineSerializer(obj.order.lines.all(), many=True).data

    def get_pdf_url(self, obj: Invoice) -> str:
        return f"/api/v1/admin/invoices/{obj.id}/pdf/"


class InvoiceCreateSerializer(serializers.Serializer[dict[str, Any]]):
    order = serializers.UUIDField()
    customer_name = serializers.CharField(required=False, allow_blank=True, default="")
    customer_email = serializers.EmailField(required=False, allow_blank=True, default="")
    customer_logo_url = serializers.URLField(required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    due_date = serializers.DateField(required=False, allow_null=True, default=None)


class InvoiceUpdateSerializer(serializers.ModelSerializer[Invoice]):
    customer_logo_url = serializers.URLField(required=False, allow_blank=True)
    seller_logo_url = serializers.URLField(required=False, allow_blank=True)

    class Meta:
        model = Invoice
        fields = (
            "customer_name",
            "customer_email",
            "customer_logo_url",
            "seller_name",
            "seller_email",
            "seller_logo_url",
            "currency",
            "subtotal",
            "discount",
            "total",
            "issue_date",
            "due_date",
            "notes",
            "status",
        )


class SendInvoiceSerializer(serializers.Serializer[dict[str, Any]]):
    to = serializers.EmailField(required=False, allow_blank=True)
    subject = serializers.CharField(required=False, allow_blank=True, default="")
    message = serializers.CharField(required=False, allow_blank=True, default="")
