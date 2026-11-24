"""Admin analytics summary — KPIs + chart series for the dashboard.

Read-only for platform admins and store sellers. All money is reported in the
store's base currency so figures are comparable regardless of how each order
was charged. Sellers only ever see numbers from stores they belong to.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Count, DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Role, User
from apps.accounts.permissions import IsAdminOrSellerRole
from apps.catalog.models import Product, Variant
from apps.currency import selectors as currency_selectors
from apps.inventory.models import StockItem
from apps.orders.models import Order, OrderLine, OrderStatus

# Orders that represent realised revenue (payment captured, not reversed).
PAID_STATUSES = [
    OrderStatus.PAID,
    OrderStatus.ROUTING,
    OrderStatus.PARTIALLY_FULFILLED,
    OrderStatus.FULFILLED,
    OrderStatus.COMPLETED,
]
LOW_STOCK_THRESHOLD = 5
TREND_DAYS = 14
TOP_PRODUCTS = 5


def _d(value: Any) -> str:
    return str((value or Decimal("0")).quantize(Decimal("0.01")))


def _scope_context(request: Request) -> tuple[bool, Any | None, list[Any]]:
    """Resolve the requester's store scope once.

    Returns ``(platform_wide, requested_tenant, member_ids)``. Platform admins
    are platform-wide unless a store is named; sellers are always restricted to
    their memberships, and naming a store they don't belong to is a 403 —
    never someone else's numbers.
    """
    user = request.user
    requested = getattr(request, "tenant", None)
    if getattr(user, "role", "") == Role.ADMIN:
        return (requested is None), requested, []
    member_ids = list(user.tenants.values_list("id", flat=True))
    if requested is not None:
        if requested.id not in member_ids:
            raise PermissionDenied("You are not a member of that store.")
        return False, requested, member_ids
    return False, None, member_ids


def _scope_q(scope: tuple[bool, Any | None, list[Any]], path: str) -> Q:
    """Q filter scoping ``path`` (e.g. ``"tenant"``, ``"order__tenant"``)."""
    platform_wide, requested, member_ids = scope
    if platform_wide:
        return Q()
    if requested is not None:
        return Q(**{path: requested})
    return Q(**{f"{path}__in": member_ids})


class AdminAnalyticsView(APIView):
    permission_classes = [IsAdminOrSellerRole]

    @extend_schema(responses={200: dict}, tags=["admin-analytics"])
    def get(self, request: Request) -> Response:
        scope = _scope_context(request)
        tenant_q = _scope_q(scope, "tenant")
        line_q = _scope_q(scope, "order__tenant")

        paid = Order.objects.filter(status__in=PAID_STATUSES).filter(tenant_q)
        revenue = paid.aggregate(
            total=Coalesce(Sum("total_base"), Value(0, output_field=DecimalField()))
        )["total"]
        paid_count = paid.count()
        orders_total = Order.objects.filter(tenant_q).count()
        avg_order = (revenue / paid_count) if paid_count else Decimal("0")

        # Orders grouped by status (pie).
        status_counts = {
            row["status"]: row["n"]
            for row in Order.objects.filter(tenant_q).values("status").annotate(n=Count("id"))
        }
        orders_by_status = [
            {"status": s.value, "label": s.label, "count": status_counts.get(s.value, 0)}
            for s in OrderStatus
            if status_counts.get(s.value, 0) > 0
        ]

        # Revenue + order count per day for the trend window (bar/line).
        start = timezone.now().date() - timedelta(days=TREND_DAYS - 1)
        by_day = {
            row["d"]: row
            for row in paid.filter(created_at__date__gte=start)
            .annotate(d=TruncDate("created_at"))
            .values("d")
            .annotate(
                revenue=Coalesce(Sum("total_base"), Value(0, output_field=DecimalField())),
                orders=Count("id"),
            )
        }
        revenue_by_day = []
        for i in range(TREND_DAYS):
            day = start + timedelta(days=i)
            row = by_day.get(day)
            revenue_by_day.append(
                {
                    "date": day.isoformat(),
                    "revenue": _d(row["revenue"] if row else Decimal("0")),
                    "orders": row["orders"] if row else 0,
                }
            )

        # Top products by units sold (bar).
        top = (
            OrderLine.objects.filter(order__status__in=PAID_STATUSES)
            .filter(line_q)
            .values("title")
            .annotate(
                quantity=Coalesce(Sum("quantity"), Value(0)),
                revenue=Coalesce(Sum("line_total_base"), Value(0, output_field=DecimalField())),
            )
            .order_by("-quantity")[:TOP_PRODUCTS]
        )
        top_products = [
            {"title": r["title"], "quantity": r["quantity"], "revenue": _d(r["revenue"])}
            for r in top
        ]

        # Fulfilment split by units (pie).
        fulfil = (
            OrderLine.objects.filter(order__status__in=PAID_STATUSES)
            .filter(line_q)
            .values("fulfillment_type")
            .annotate(quantity=Coalesce(Sum("quantity"), Value(0)))
        )
        fulfillment_split = [
            {"type": r["fulfillment_type"], "quantity": r["quantity"]} for r in fulfil
        ]

        # Low-stock active variants (available = on_hand - reserved <= threshold).
        avail = dict(
            StockItem.objects.filter(_scope_q(scope, "warehouse__tenant"))
            .values("variant")
            .annotate(a=Sum(F("on_hand") - F("reserved")))
            .values_list("variant", "a")
        )
        low_stock = sum(
            1
            for vid in Variant.objects.filter(is_active=True)
            .filter(_scope_q(scope, "product__tenant"))
            .values_list("id", flat=True)
            if (avail.get(vid) or 0) <= LOW_STOCK_THRESHOLD
        )

        # Customers who have ordered from the in-scope store(s).
        customers = (
            User.objects.filter(role=Role.CUSTOMER)
            .filter(_scope_q(scope, "orders__tenant"))
            .distinct()
            .count()
        )

        return Response(
            {
                "kpis": {
                    "currency": currency_selectors.base_code(),
                    "revenue": _d(revenue),
                    "orders": orders_total,
                    "paid_orders": paid_count,
                    "avg_order_value": _d(avg_order),
                    "products": Product.objects.filter(is_active=True).filter(tenant_q).count(),
                    "customers": customers,
                    "low_stock": low_stock,
                },
                "orders_by_status": orders_by_status,
                "revenue_by_day": revenue_by_day,
                "top_products": top_products,
                "fulfillment_split": fulfillment_split,
            }
        )
