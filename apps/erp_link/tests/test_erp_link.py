"""ERP ↔ marketplace link: service-key auth, publication, stock, outbound events."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal

import pytest
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.cart import services as cart_services
from apps.cart.tests.factories import setup_currencies
from apps.catalog.models import Product, Variant
from apps.erp_link import services as link_services
from apps.erp_link.models import (
    ERPWebhookDelivery,
    ErpWebhookDeliveryStatus,
    ErpWebhookEvent,
    ReconciliationReport,
)
from apps.inventory.models import StockItem
from apps.orders import services as order_services
from apps.payments import services as payment_services
from apps.tenants.models import TenantType
from apps.tenants.services import create_tenant, issue_api_key


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.fixture
def erp_store(db):
    store = create_tenant(
        name="ERP Subscriber",
        slug="erp-store",
        type=TenantType.ERP_SUBSCRIBER,
        erp_business_id="biz-uuid-123",
    )
    _, raw_key = issue_api_key(tenant=store, name="test-erp")
    return store, raw_key


@pytest.fixture
def independent_store(db):
    store = create_tenant(name="Independent", slug="ind-store")
    _, raw_key = issue_api_key(tenant=store, name="test-ind")
    return store, raw_key


def _setup_currencies() -> None:
    setup_currencies()


def _publish_payload(**overrides):
    payload = {
        "erp_product_id": "prod-erp-1",
        "title": "Agbada Deluxe",
        "description": "Handwoven",
        "status": "published",
        "category_name": "Agbada",
        "brand_name": "Sartorial",
        "variants": [
            {
                "erp_variant_id": "var-erp-1",
                "sku": "AGB-XL-BLU",
                "price": "85000.00",
                "options": [
                    {"name": "Size", "value": "XL"},
                    {"name": "Color", "value": "Blue"},
                ],
            },
            {
                "erp_variant_id": "var-erp-2",
                "sku": "AGB-L-BLU",
                "price": "80000.00",
                "options": [
                    {"name": "Size", "value": "L"},
                    {"name": "Color", "value": "Blue"},
                ],
            },
        ],
    }
    payload.update(overrides)
    return payload


def _auth(raw_key: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {raw_key}"}


# --- Stage 1: authentication -------------------------------------------------


@pytest.mark.django_db
def test_publish_requires_service_key(client) -> None:
    resp = client.post("/api/v1/erp/catalog/sync/", _publish_payload(), format="json")
    assert resp.status_code in (401, 403)


@pytest.mark.django_db
def test_publish_rejects_bad_key(client, erp_store) -> None:
    resp = client.post(
        "/api/v1/erp/catalog/sync/",
        _publish_payload(),
        format="json",
        **_auth("sk_definitely-not-a-real-key"),
    )
    assert resp.status_code == 401


@pytest.mark.django_db
def test_publish_rejects_independent_store_key(client, independent_store) -> None:
    _, raw_key = independent_store
    resp = client.post(
        "/api/v1/erp/catalog/sync/", _publish_payload(), format="json", **_auth(raw_key)
    )
    assert resp.status_code == 403
    assert not Product.objects.filter(erp_product_id="prod-erp-1").exists()


@pytest.mark.django_db
def test_publish_rejects_suspended_store(client, erp_store) -> None:
    store, raw_key = erp_store
    store.status = "suspended"
    store.save(update_fields=["status"])
    resp = client.post(
        "/api/v1/erp/catalog/sync/", _publish_payload(), format="json", **_auth(raw_key)
    )
    assert resp.status_code == 401


@pytest.mark.django_db
def test_publish_accepts_api_key_header(client, erp_store) -> None:
    _, raw_key = erp_store
    resp = client.post(
        "/api/v1/erp/catalog/sync/",
        _publish_payload(),
        format="json",
        HTTP_X_API_KEY=raw_key,
    )
    assert resp.status_code == 201


# --- Stage 2: publication -----------------------------------------------------


@pytest.mark.django_db
def test_publish_creates_product_and_variants(client, erp_store) -> None:
    store, raw_key = erp_store
    resp = client.post(
        "/api/v1/erp/catalog/sync/", _publish_payload(), format="json", **_auth(raw_key)
    )
    assert resp.status_code == 201
    product = Product.objects.get(erp_product_id="prod-erp-1")
    assert product.tenant_id == store.id
    assert product.is_active is True
    assert product.category is not None and product.category.name == "Agbada"
    assert product.brand is not None and product.brand.name == "Sartorial"
    assert product.variants.count() == 2
    xl = product.variants.get(sku="AGB-XL-BLU")
    assert xl.erp_variant_id == "var-erp-1"
    assert xl.price == Decimal("85000.00")
    assert xl.options_key != ""
    assert {o.option_value.value for o in xl.variant_options.all()} == {"XL", "Blue"}


@pytest.mark.django_db
def test_publish_applies_erp_discount_and_vat(client, erp_store) -> None:
    _, raw_key = erp_store
    payload = _publish_payload(discount="15", vat_percent="7.5")
    resp = client.post("/api/v1/erp/catalog/sync/", payload, format="json", **_auth(raw_key))
    assert resp.status_code == 201
    product = Product.objects.get(erp_product_id="prod-erp-1")
    assert product.discount_percent == Decimal("15.00")
    assert product.vat_rate_percent == Decimal("7.50")
    assert product.vat_flat_amount is None


@pytest.mark.django_db
def test_publish_is_idempotent_and_updates_in_place(client, erp_store) -> None:
    store, raw_key = erp_store
    first = client.post(
        "/api/v1/erp/catalog/sync/", _publish_payload(), format="json", **_auth(raw_key)
    )
    assert first.status_code == 201
    changed = _publish_payload(
        title="Agbada Deluxe v2",
        variants=[
            {
                "erp_variant_id": "var-erp-1",
                "sku": "AGB-XL-BLU",
                "price": "90000.00",
                "options": [
                    {"name": "Size", "value": "XL"},
                    {"name": "Color", "value": "Blue"},
                ],
            },
            {
                "erp_variant_id": "var-erp-2",
                "sku": "AGB-L-BLU",
                "price": "81000.00",
                "options": [
                    {"name": "Size", "value": "L"},
                    {"name": "Color", "value": "Blue"},
                ],
            },
        ],
    )
    second = client.post("/api/v1/erp/catalog/sync/", changed, format="json", **_auth(raw_key))
    assert second.status_code == 200
    assert Product.objects.filter(erp_product_id="prod-erp-1").count() == 1
    product = Product.objects.get(erp_product_id="prod-erp-1")
    assert product.title == "Agbada Deluxe v2"
    assert product.variants.get(sku="AGB-XL-BLU").price == Decimal("90000.00")


@pytest.mark.django_db
def test_publish_archives_missing_variants_and_product(client, erp_store) -> None:
    store, raw_key = erp_store
    client.post("/api/v1/erp/catalog/sync/", _publish_payload(), format="json", **_auth(raw_key))
    reduced = _publish_payload(
        variants=[
            {
                "erp_variant_id": "var-erp-1",
                "sku": "AGB-XL-BLU",
                "price": "85000.00",
                "options": [
                    {"name": "Size", "value": "XL"},
                    {"name": "Color", "value": "Blue"},
                ],
            }
        ]
    )
    resp = client.post("/api/v1/erp/catalog/sync/", reduced, format="json", **_auth(raw_key))
    assert resp.status_code == 200
    assert not Variant.objects.get(sku="AGB-L-BLU").is_active
    assert resp.json()["deactivated_variants"] == 1

    archived = _publish_payload(status="archived")
    resp = client.post("/api/v1/erp/catalog/sync/", archived, format="json", **_auth(raw_key))
    assert resp.status_code == 200
    assert not Product.objects.get(erp_product_id="prod-erp-1").is_active


@pytest.mark.django_db
def test_publish_rejects_erp_id_collision_across_stores(
    client, erp_store, independent_store
) -> None:
    store, raw_key = erp_store
    other_store, _ = independent_store
    client.post("/api/v1/erp/catalog/sync/", _publish_payload(), format="json", **_auth(raw_key))
    # Simulate the same ERP id showing up bound to another tenant directly.
    Product.objects.filter(erp_product_id="prod-erp-1").update(tenant=other_store)
    resp = client.post(
        "/api/v1/erp/catalog/sync/", _publish_payload(), format="json", **_auth(raw_key)
    )
    assert resp.status_code == 409


@pytest.mark.django_db
def test_stock_push_and_snapshot(client, erp_store) -> None:
    store, raw_key = erp_store
    client.post("/api/v1/erp/catalog/sync/", _publish_payload(), format="json", **_auth(raw_key))
    resp = client.post(
        "/api/v1/erp/inventory/",
        {"items": [{"sku": "AGB-XL-BLU", "quantity": 12}, {"sku": "UNKNOWN", "quantity": 3}]},
        format="json",
        **_auth(raw_key),
    )
    assert resp.status_code == 200
    results = {r["sku"]: r for r in resp.json()["results"]}
    assert results["AGB-XL-BLU"]["status"] == "ok"
    assert results["UNKNOWN"]["status"] == "unknown_sku"

    snap = client.get("/api/v1/erp/inventory/", **_auth(raw_key))
    assert snap.status_code == 200
    rows = {r["sku"]: r for r in snap.json()["inventory"]}
    assert rows["AGB-XL-BLU"]["on_hand"] == 12
    assert rows["AGB-XL-BLU"]["available"] == 12

    variant = Variant.objects.get(sku="AGB-XL-BLU")
    assert StockItem.objects.filter(variant=variant, warehouse__code="erp").count() == 1


# --- Stage 3: outbound webhooks -----------------------------------------------


def _cart_with(store, sku="AGB-XL-BLU", qty=1):
    _setup_currencies()
    link_services.set_stock_levels(tenant=store, items=[{"sku": sku, "quantity": 100}])
    variant = Variant.objects.get(sku=sku)
    cart = cart_services.get_or_create_cart(session_key="erp-test", tenant=store)
    cart_services.add_item(cart, variant_id=str(variant.id), quantity=qty)
    cart_services.set_shipping(
        cart, {"name": "Ada", "line1": "1 St", "city": "Lagos", "country": "NG"}
    )
    return cart


@pytest.mark.django_db
def test_checkout_queues_order_created_webhook_for_erp_store(client, erp_store) -> None:
    store, raw_key = erp_store
    client.post("/api/v1/erp/catalog/sync/", _publish_payload(), format="json", **_auth(raw_key))
    cart = _cart_with(store, qty=2)

    with TestCase.captureOnCommitCallbacks(execute=True):
        order = order_services.checkout(cart, idempotency_key="erp-order-1", currency="USD")

    deliveries = ERPWebhookDelivery.objects.filter(event=ErpWebhookEvent.ORDER_CREATED)
    assert deliveries.count() == 1
    delivery = deliveries.first()
    assert delivery.tenant_id == store.id
    assert delivery.payload["order_number"] == order.number
    assert delivery.payload["erp_business_id"] == "biz-uuid-123"
    line = delivery.payload["lines"][0]
    assert line["sku"] == "AGB-XL-BLU"
    assert line["erp_variant_id"] == "var-erp-1"
    assert line["quantity"] == 2


@pytest.mark.django_db
def test_independent_store_checkout_queues_nothing(client, independent_store) -> None:
    store, raw_key = independent_store
    _setup_currencies()
    # Independent stores can't publish via the ERP API; sell a native product.
    from apps.cart.tests.factories import make_variant
    from apps.inventory.services import set_stock

    variant = make_variant("10.00", stock=0)
    variant.product.tenant = store
    variant.product.save(update_fields=["tenant"])
    set_stock(variant, 5)  # stock in the independent store's default warehouse
    cart = cart_services.get_or_create_cart(session_key="ind-test", tenant=store)
    cart_services.add_item(cart, variant_id=str(variant.id), quantity=1)

    with TestCase.captureOnCommitCallbacks(execute=True):
        order_services.checkout(cart, idempotency_key="ind-order-1", currency="USD")

    assert ERPWebhookDelivery.objects.count() == 0


@pytest.mark.django_db
def test_payment_success_queues_payment_succeeded_webhook(client, erp_store) -> None:
    store, raw_key = erp_store
    client.post("/api/v1/erp/catalog/sync/", _publish_payload(), format="json", **_auth(raw_key))
    cart = _cart_with(store)
    with TestCase.captureOnCommitCallbacks(execute=True):
        order = order_services.checkout(cart, idempotency_key="erp-order-2", currency="USD")
    ERPWebhookDelivery.objects.all().delete()  # ignore order.created

    payment = order.payments.first()
    with TestCase.captureOnCommitCallbacks(execute=True):
        payment_services.confirm_mock_payment(payment)

    deliveries = ERPWebhookDelivery.objects.filter(event=ErpWebhookEvent.PAYMENT_SUCCEEDED)
    assert deliveries.count() == 1
    assert deliveries.first().payload["order_number"] == order.number


@pytest.mark.django_db
def test_delivery_marks_delivered_on_2xx(erp_store, monkeypatch, settings) -> None:
    store, _ = erp_store
    settings.SARTORIAL_ERP_BASE_URL = "https://erp.example.com"
    settings.SARTORIAL_ERP_API_KEY = "integration-secret"
    delivery = ERPWebhookDelivery.objects.create(
        event=ErpWebhookEvent.ORDER_CREATED,
        tenant=store,
        payload={"order_number": "ORD-1"},
    )

    class FakeResp:
        status_code = 200
        text = "ok"

    monkeypatch.setattr("apps.erp_link.tasks.requests.post", lambda *a, **kw: FakeResp())
    from apps.erp_link import tasks

    result = tasks.deliver_erp_webhook(str(delivery.id))
    assert result["status"] == "delivered"
    delivery.refresh_from_db()
    assert delivery.status == ErpWebhookDeliveryStatus.DELIVERED
    assert delivery.delivered_at is not None


@pytest.mark.django_db
def test_delivery_retries_on_5xx_and_gives_up_after_max(erp_store, monkeypatch, settings) -> None:
    store, _ = erp_store
    settings.SARTORIAL_ERP_BASE_URL = "https://erp.example.com"
    settings.SARTORIAL_ERP_API_KEY = "integration-secret"
    delivery = ERPWebhookDelivery.objects.create(
        event=ErpWebhookEvent.ORDER_CREATED,
        tenant=store,
        payload={"order_number": "ORD-2"},
    )

    class FakeResp:
        status_code = 503
        text = "erp down"

    monkeypatch.setattr("apps.erp_link.tasks.requests.post", lambda *a, **kw: FakeResp())
    from apps.erp_link import tasks

    result = tasks.deliver_erp_webhook(str(delivery.id))
    assert result["status"] == "retry_scheduled"
    delivery.refresh_from_db()
    assert delivery.attempts == 1
    assert delivery.status == ErpWebhookDeliveryStatus.PENDING
    assert delivery.next_retry_at is not None

    # Simulate exhausting the retry budget.
    delivery.attempts = 7
    delivery.save(update_fields=["attempts"])
    result = tasks.deliver_erp_webhook(str(delivery.id))
    assert result["status"] == "retry_scheduled"
    delivery.refresh_from_db()
    assert delivery.status == ErpWebhookDeliveryStatus.FAILED
    assert delivery.next_retry_at is None


@pytest.mark.django_db
def test_delivery_4xx_is_permanent(erp_store, monkeypatch, settings) -> None:
    store, _ = erp_store
    settings.SARTORIAL_ERP_BASE_URL = "https://erp.example.com"
    settings.SARTORIAL_ERP_API_KEY = "integration-secret"
    delivery = ERPWebhookDelivery.objects.create(
        event=ErpWebhookEvent.ORDER_CREATED,
        tenant=store,
        payload={"order_number": "ORD-3"},
    )

    class FakeResp:
        status_code = 422
        text = "bad payload"

    monkeypatch.setattr("apps.erp_link.tasks.requests.post", lambda *a, **kw: FakeResp())
    from apps.erp_link import tasks

    result = tasks.deliver_erp_webhook(str(delivery.id))
    assert result["status"] == "failed"
    delivery.refresh_from_db()
    assert delivery.status == ErpWebhookDeliveryStatus.FAILED
    assert delivery.attempts == 1


@pytest.mark.django_db
def test_delivery_skips_when_erp_not_configured(erp_store, settings) -> None:
    store, _ = erp_store
    settings.SARTORIAL_ERP_BASE_URL = ""
    settings.SARTORIAL_ERP_API_KEY = ""
    delivery = ERPWebhookDelivery.objects.create(
        event=ErpWebhookEvent.ORDER_CREATED,
        tenant=store,
        payload={"order_number": "ORD-4"},
    )
    from apps.erp_link import tasks

    # Need to also reset the cached settings access in services.
    result = tasks.deliver_erp_webhook(str(delivery.id))
    assert result["status"] == "not_configured"
    delivery.refresh_from_db()
    assert delivery.status == ErpWebhookDeliveryStatus.PENDING  # untouched, keeps retrying


@pytest.mark.django_db
def test_outbound_payload_is_signed(erp_store, settings) -> None:
    store, _ = erp_store
    settings.SARTORIAL_ERP_BASE_URL = "https://erp.example.com"
    settings.SARTORIAL_ERP_API_KEY = "integration-secret"
    delivery = ERPWebhookDelivery.objects.create(
        event=ErpWebhookEvent.ORDER_CREATED,
        tenant=store,
        payload={"order_number": "ORD-5"},
    )
    url, body, headers = link_services.build_delivery_request(delivery)
    expected = hmac.new(b"integration-secret", body, hashlib.sha256).hexdigest()
    assert url == "https://erp.example.com/api/v1/ecommerce/webhooks/marketplace/"
    assert headers["X-Marketplace-Signature"] == f"sha256={expected}"
    assert headers["X-Marketplace-Event-Id"] == str(delivery.event_id)
    decoded = json.loads(body)
    assert decoded["event"] == "order.created"
    assert decoded["data"]["order_number"] == "ORD-5"


# --- Stage 4: reconciliation ---------------------------------------------------


@pytest.mark.django_db
def test_reconciliation_reports_matching_stock(client, erp_store, settings, monkeypatch) -> None:
    store, raw_key = erp_store
    settings.SARTORIAL_ERP_BASE_URL = "https://erp.example.com"
    settings.SARTORIAL_ERP_API_KEY = "integration-secret"
    client.post("/api/v1/erp/catalog/sync/", _publish_payload(), format="json", **_auth(raw_key))
    client.post(
        "/api/v1/erp/inventory/",
        {"items": [{"sku": "AGB-XL-BLU", "quantity": 9}]},
        format="json",
        **_auth(raw_key),
    )

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "inventory": [
                    {"sku": "AGB-XL-BLU", "erp_variant_id": "var-erp-1", "available": 9},
                    {"sku": "AGB-L-BLU", "erp_variant_id": "var-erp-2", "available": 0},
                ]
            }

    monkeypatch.setattr("apps.erp_link.tasks.requests.get", lambda *a, **kw: FakeResp())
    from apps.erp_link import tasks

    summary = tasks.reconcile_erp_inventory()
    assert summary["tenants"] == 1
    assert summary["mismatches"] == 0
    report = ReconciliationReport.objects.get(tenant=store)
    assert report.ok is True
    assert report.checked == 2


@pytest.mark.django_db
def test_reconciliation_flags_stock_drift(client, erp_store, settings, monkeypatch) -> None:
    store, raw_key = erp_store
    settings.SARTORIAL_ERP_BASE_URL = "https://erp.example.com"
    settings.SARTORIAL_ERP_API_KEY = "integration-secret"
    client.post("/api/v1/erp/catalog/sync/", _publish_payload(), format="json", **_auth(raw_key))
    client.post(
        "/api/v1/erp/inventory/",
        {"items": [{"sku": "AGB-XL-BLU", "quantity": 9}]},
        format="json",
        **_auth(raw_key),
    )

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"inventory": [{"sku": "AGB-XL-BLU", "available": 4}]}

    monkeypatch.setattr("apps.erp_link.tasks.requests.get", lambda *a, **kw: FakeResp())
    from apps.erp_link import tasks

    summary = tasks.reconcile_erp_inventory()
    assert summary["mismatches"] == 1
    report = ReconciliationReport.objects.get(tenant=store)
    assert report.ok is False
    mismatch = report.mismatches[0]
    assert mismatch["sku"] == "AGB-XL-BLU"
    assert mismatch["difference"] == 5


@pytest.mark.django_db
def test_retry_webhooks_picks_up_due_deliveries(erp_store, monkeypatch, settings) -> None:
    store, _ = erp_store
    settings.SARTORIAL_ERP_BASE_URL = "https://erp.example.com"
    settings.SARTORIAL_ERP_API_KEY = "integration-secret"
    due = ERPWebhookDelivery.objects.create(
        event=ErpWebhookEvent.ORDER_CREATED,
        tenant=store,
        payload={"order_number": "ORD-6"},
        next_retry_at=timezone.now() - timedelta(minutes=1),
    )
    fresh = ERPWebhookDelivery.objects.create(
        event=ErpWebhookEvent.ORDER_CREATED,
        tenant=store,
        payload={"order_number": "ORD-7"},
        next_retry_at=timezone.now() + timedelta(hours=1),
    )

    class FakeResp:
        status_code = 200
        text = "ok"

    monkeypatch.setattr("apps.erp_link.tasks.requests.post", lambda *a, **kw: FakeResp())
    from apps.erp_link import tasks

    result = tasks.retry_erp_webhooks()
    assert result["attempted"] == 1
    due.refresh_from_db()
    fresh.refresh_from_db()
    assert due.status == ErpWebhookDeliveryStatus.DELIVERED
    assert fresh.status == ErpWebhookDeliveryStatus.PENDING
