from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.invoices.models import Invoice, InvoiceStatus
from apps.notifications.channels.email import MemoryEmailBackend
from apps.orders.models import Order, OrderLine
from apps.tenants.models import Tenant, TenantMembership
from apps.tenants.services import create_tenant

User = get_user_model()


@pytest.fixture
def client() -> APIClient:
    return APIClient()


def _seller_with_store(slug: str) -> tuple[Any, Tenant]:
    seller = User.objects.create_user(
        email=f"{slug}@example.com", password="Pass12345!", role=Role.SELLER
    )
    store = create_tenant(name=slug.title(), slug=slug)
    TenantMembership.objects.create(tenant=store, user=seller, role="owner")
    return seller, store


def _order(store: Tenant, *, number: str = "IC-INV001") -> Order:
    order = Order.objects.create(
        tenant=store,
        number=number,
        status="paid",
        base_currency="USD",
        currency="USD",
        subtotal_base=Decimal("25.00"),
        discount_base=Decimal("0"),
        total_base=Decimal("25.00"),
        subtotal_charged=Decimal("25.00"),
        discount_charged=Decimal("0"),
        total_charged=Decimal("25.00"),
        contact_email="buyer@example.com",
        contact_name="Buyer",
        ship_name="Buyer",
    )
    OrderLine.objects.create(
        order=order,
        sku="INV-SKU",
        title="Linen dress",
        quantity=1,
        unit_price_base=Decimal("25.00"),
        line_total_base=Decimal("25.00"),
        unit_price_charged=Decimal("25.00"),
        line_total_charged=Decimal("25.00"),
        fulfillment_type="internal",
    )
    return order


@pytest.mark.django_db
def test_seller_creates_invoice_and_downloads_pdf(client: APIClient) -> None:
    seller, store = _seller_with_store("invoice-store")
    order = _order(store)
    client.force_authenticate(seller)

    created = client.post(
        "/api/v1/admin/invoices/",
        {
            "order": str(order.id),
            "customer_name": "Ada Buyer",
            "customer_logo_url": "",
            "notes": "Thank you",
        },
        format="json",
        HTTP_X_TENANT_SLUG=store.slug,
    )
    assert created.status_code == 201
    invoice_id = created.json()["id"]
    assert created.json()["number"].startswith("INV-")

    pdf = client.get(f"/api/v1/admin/invoices/{invoice_id}/pdf/", HTTP_X_TENANT_SLUG=store.slug)
    assert pdf.status_code == 200
    assert pdf["Content-Type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")

    duplicate = client.post(
        "/api/v1/admin/invoices/",
        {"order": str(order.id)},
        format="json",
        HTTP_X_TENANT_SLUG=store.slug,
    )
    assert duplicate.status_code == 400


@pytest.mark.django_db
def test_invoice_email_attaches_pdf_and_marks_sent(client: APIClient, settings: Any) -> None:
    settings.NOTIFICATIONS_EMAIL_BACKEND = "memory"
    MemoryEmailBackend.outbox.clear()
    seller, store = _seller_with_store("invoice-email-store")
    order = _order(store, number="IC-INV002")
    invoice = Invoice.objects.create(
        tenant=store,
        order=order,
        customer_email="buyer@example.com",
        seller_name="Invoice Store",
        currency="USD",
        total=Decimal("25.00"),
    )
    client.force_authenticate(seller)

    response = client.post(
        f"/api/v1/admin/invoices/{invoice.id}/send/",
        {"to": "buyer@example.com", "message": "Please pay on receipt."},
        format="json",
        HTTP_X_TENANT_SLUG=store.slug,
    )
    assert response.status_code == 200
    invoice.refresh_from_db()
    assert invoice.status == InvoiceStatus.SENT
    assert len(MemoryEmailBackend.outbox) == 1
    sent = MemoryEmailBackend.outbox[0]
    assert sent.attachments[0].filename == f"{invoice.number}.pdf"
    assert sent.attachments[0].content.startswith(b"%PDF")


@pytest.mark.django_db
def test_seller_cannot_invoice_foreign_order(client: APIClient) -> None:
    seller, store = _seller_with_store("invoice-owner-store")
    other = create_tenant(name="Other", slug="invoice-other-store")
    order = _order(other, number="IC-INV003")
    client.force_authenticate(seller)

    response = client.post(
        "/api/v1/admin/invoices/",
        {"order": str(order.id)},
        format="json",
        HTTP_X_TENANT_SLUG=store.slug,
    )
    assert response.status_code == 403
