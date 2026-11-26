from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Count, DecimalField, Sum, Value
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdminOrSellerRole
from apps.common.analytics_views import PAID_STATUSES, _d, _scope_context, _scope_q
from apps.currency import selectors as currency_selectors
from apps.invoices.models import Invoice, InvoiceStatus
from apps.orders.models import Order, OrderLine, OrderStatus

REPORT_DAYS = 30
TOP_PRODUCTS = 10


def _parse_date(value: str | None, fallback: date) -> date:
    if not value:
        return fallback
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"Invalid date '{value}'. Use YYYY-MM-DD.") from exc


def _sum(queryset: Any, field: str) -> Decimal:
    value = queryset.aggregate(total=Coalesce(Sum(field), Value(0, output_field=DecimalField())))[
        "total"
    ]
    return value or Decimal("0")


class SalesReportView(APIView):
    permission_classes = [IsAdminOrSellerRole]

    @extend_schema(responses={200: dict}, tags=["admin-sales-report"])
    def get(self, request: Request) -> Response:
        today = timezone.localdate()
        start = _parse_date(
            request.query_params.get("from"), today - timedelta(days=REPORT_DAYS - 1)
        )
        end = _parse_date(request.query_params.get("to"), today)
        if start > end:
            raise ValidationError("'from' must be on or before 'to'.")

        scope = _scope_context(request)
        tenant_q = _scope_q(scope, "tenant")
        line_q = _scope_q(scope, "order__tenant")
        status_filter = request.query_params.get("status", "").strip()

        orders = Order.objects.filter(tenant_q, created_at__date__range=(start, end))
        if status_filter:
            orders = orders.filter(status=status_filter)
        paid = orders.filter(status__in=PAID_STATUSES)

        summary = {
            "currency": currency_selectors.base_code(),
            "from": start.isoformat(),
            "to": end.isoformat(),
            "orders": orders.count(),
            "paid_orders": paid.count(),
            "gross": _d(_sum(orders, "subtotal_base")),
            "discounts": _d(_sum(orders, "discount_base")),
            "vat": _d(_sum(orders, "vat_base")),
            "net": _d(_sum(orders, "total_base")),
            "revenue": _d(_sum(paid, "total_base")),
            "refunds": _d(_sum(orders.filter(status=OrderStatus.REFUNDED), "total_base")),
            "avg_order_value": _d(
                (_sum(paid, "total_base") / paid.count()) if paid.count() else Decimal("0")
            ),
        }

        status_rows = {
            row["status"]: row
            for row in orders.values("status").annotate(
                count=Count("id"),
                total=Coalesce(Sum("total_base"), Value(0, output_field=DecimalField())),
            )
        }
        by_status = [
            {
                "status": option.value,
                "label": option.label,
                "count": status_rows.get(option.value, {}).get("count", 0),
                "total": _d(status_rows.get(option.value, {}).get("total") or Decimal("0")),
            }
            for option in OrderStatus
            if status_rows.get(option.value, {}).get("count", 0) > 0
        ]

        day_rows = {
            row["day"]: row
            for row in orders.annotate(day=TruncDate("created_at"))
            .values("day")
            .annotate(
                orders=Count("id"),
                gross=Coalesce(Sum("subtotal_base"), Value(0, output_field=DecimalField())),
                discounts=Coalesce(Sum("discount_base"), Value(0, output_field=DecimalField())),
                vat=Coalesce(Sum("vat_base"), Value(0, output_field=DecimalField())),
                net=Coalesce(Sum("total_base"), Value(0, output_field=DecimalField())),
            )
        }
        by_day = []
        cursor = start
        while cursor <= end:
            row = day_rows.get(cursor, {})
            by_day.append(
                {
                    "date": cursor.isoformat(),
                    "orders": row.get("orders", 0),
                    "gross": _d(row.get("gross") or Decimal("0")),
                    "discounts": _d(row.get("discounts") or Decimal("0")),
                    "vat": _d(row.get("vat") or Decimal("0")),
                    "net": _d(row.get("net") or Decimal("0")),
                }
            )
            cursor += timedelta(days=1)

        top_rows = (
            OrderLine.objects.filter(order__status__in=PAID_STATUSES)
            .filter(line_q)
            .filter(order__created_at__date__range=(start, end))
            .values("title")
            .annotate(
                quantity=Coalesce(Sum("quantity"), Value(0)),
                revenue=Coalesce(Sum("line_total_base"), Value(0, output_field=DecimalField())),
            )
            .order_by("-revenue")[:TOP_PRODUCTS]
        )
        top_products = [
            {
                "title": row["title"],
                "quantity": row["quantity"],
                "revenue": _d(row["revenue"]),
            }
            for row in top_rows
        ]

        invoice_rows = (
            Invoice.objects.filter(tenant_q, created_at__date__range=(start, end))
            .values("status")
            .annotate(
                count=Count("id"),
                total=Coalesce(Sum("total"), Value(0, output_field=DecimalField())),
            )
        )
        invoice_counts = {row["status"]: row for row in invoice_rows}
        invoices = [
            {
                "status": option.value,
                "label": option.label,
                "count": invoice_counts.get(option.value, {}).get("count", 0),
                "total": _d(invoice_counts.get(option.value, {}).get("total") or Decimal("0")),
            }
            for option in InvoiceStatus
        ]

        return Response(
            {
                "summary": summary,
                "by_day": by_day,
                "by_status": by_status,
                "top_products": top_products,
                "invoices": invoices,
            }
        )
