from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.invoices.models import InvoiceStatus
from apps.orders.models import Order, OrderStatus
from apps.tenants.models import TenantMembership
from apps.tenants.services import create_tenant

User = get_user_model()
SALES_REPORT_URL = "/api/v1/admin/sales-report/"


@pytest.fixture
def client() -> APIClient:
    return APIClient()


def _seller_with_store(slug: str):
    seller = User.objects.create_user(
        email=f"{slug}@example.com", password="Pass12345!", role=Role.SELLER
    )
    store = create_tenant(name=slug.replace("-", " ").title(), slug=slug)
    TenantMembership.objects.create(tenant=store, user=seller, role="owner")
    return seller, store


def _order(tenant, status: str, total: str, vat: str = "0", discount: str = "0") -> Order:
    return Order.objects.create(
        tenant=tenant,
        status=status,
        base_currency="NGN",
        currency="NGN",
        subtotal_base=total,
        discount_base=discount,
        vat_base=vat,
        total_base=total,
    )


@pytest.mark.django_db
def test_requires_admin_or_seller(client: APIClient) -> None:
    assert client.get(SALES_REPORT_URL).status_code in (401, 403)
    customer = User.objects.create_user(
        email="customer@example.com", password="x", role=Role.CUSTOMER
    )
    client.force_authenticate(customer)
    assert client.get(SALES_REPORT_URL).status_code == 403


@pytest.mark.django_db
def test_seller_sees_only_own_totals(client: APIClient) -> None:
    seller, store = _seller_with_store("report-store")
    other = create_tenant(name="Other", slug="other-report-store")
    _order(store, OrderStatus.PAID, "990.00", vat="90", discount="100")
    _order(other, OrderStatus.PAID, "5000.00", vat="500")

    today = timezone.localdate()
    client.force_authenticate(seller)
    resp = client.get(
        SALES_REPORT_URL,
        {"from": (today - timedelta(days=1)).isoformat(), "to": today.isoformat()},
        HTTP_X_TENANT_SLUG=store.slug,
    )
    assert resp.status_code == 200
    assert resp.data["summary"]["revenue"] == "990.00"
    assert resp.data["summary"]["net"] == "990.00"
    assert resp.data["summary"]["vat"] == "90.00"
    assert resp.data["summary"]["discounts"] == "100.00"
    assert resp.data["summary"]["paid_orders"] == 1
    assert [row["label"] for row in resp.data["invoices"]] == [
        status.label for status in InvoiceStatus
    ]


@pytest.mark.django_db
def test_seller_cannot_read_foreign_store(client: APIClient) -> None:
    seller, _ = _seller_with_store("report-store")
    create_tenant(name="Other", slug="other-report-store")
    client.force_authenticate(seller)
    resp = client.get(SALES_REPORT_URL, HTTP_X_TENANT_SLUG="other-report-store")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_invalid_date_range_is_rejected(client: APIClient) -> None:
    seller, _ = _seller_with_store("report-store")
    client.force_authenticate(seller)
    resp = client.get(SALES_REPORT_URL, {"from": "2026-40-01"})
    assert resp.status_code == 400
