"""Cross-store isolation: one store's data never leaks into another's."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.cart import services as cart_services
from apps.catalog.tests.factories import ProductFactory, VariantFactory
from apps.common.exceptions import DomainError
from apps.orders import services as order_services
from apps.promotions.models import Coupon
from apps.storeconfig import selectors
from apps.storeconfig import services as config_services
from apps.tenants.services import create_tenant, get_effective_tenant


@pytest.mark.django_db
def test_same_slug_allowed_across_tenants() -> None:
    a = create_tenant(name="A", slug="a")
    b = create_tenant(name="B", slug="b")
    ProductFactory(slug="shirts", tenant=a)
    ProductFactory(slug="shirts", tenant=b)  # per-tenant uniqueness: no clash


@pytest.mark.django_db
def test_public_catalog_scoped_to_header_tenant() -> None:
    a = create_tenant(name="A", slug="store-a")
    b = create_tenant(name="B", slug="store-b")
    ProductFactory(title="A-thing", tenant=a)
    ProductFactory(title="B-thing", tenant=b)

    client = APIClient()
    resp_b = client.get("/api/v1/catalog/products/", HTTP_X_TENANT_SLUG="store-b")
    assert resp_b.status_code == 200
    titles_b = [row["title"] for row in resp_b.data["results"]]
    assert titles_b == ["B-thing"]

    resp_a = client.get("/api/v1/catalog/products/", HTTP_X_TENANT_SLUG="store-a")
    titles_a = [row["title"] for row in resp_a.data["results"]]
    assert titles_a == ["A-thing"]


@pytest.mark.django_db
def test_product_detail_hidden_cross_store() -> None:
    b = create_tenant(name="B", slug="store-b")
    product = ProductFactory(title="B-only", tenant=b)

    client = APIClient()
    assert (
        client.get(
            f"/api/v1/catalog/products/{product.slug}/", HTTP_X_TENANT_SLUG="store-b"
        ).status_code
        == 200
    )
    assert client.get(f"/api/v1/catalog/products/{product.slug}/").status_code == 404


@pytest.mark.django_db
def test_carts_are_per_store_and_items_cannot_cross() -> None:
    a = create_tenant(name="A", slug="a")
    b = create_tenant(name="B", slug="b")
    variant_a = VariantFactory(product=ProductFactory(tenant=a))

    cart_a = cart_services.get_or_create_cart(session_key="same-sess", tenant=a)
    cart_b = cart_services.get_or_create_cart(session_key="same-sess", tenant=b)
    assert cart_a.id != cart_b.id
    assert cart_a.tenant_id == a.id and cart_b.tenant_id == b.id

    cart_services.add_item(cart_a, variant_id=str(variant_a.id), quantity=1)
    with pytest.raises(DomainError):
        cart_services.add_item(cart_b, variant_id=str(variant_a.id), quantity=1)


@pytest.mark.django_db
def test_checkout_carries_cart_tenant_onto_order() -> None:
    from apps.inventory.services import set_stock

    a = create_tenant(name="A", slug="a")
    variant = VariantFactory(product=ProductFactory(tenant=a))
    set_stock(variant, 10)
    cart = cart_services.get_or_create_cart(session_key="co-sess", tenant=a)
    cart_services.add_item(cart, variant_id=str(variant.id), quantity=1)
    order = order_services.checkout(cart, idempotency_key="iso-1")
    assert order.tenant_id == a.id


@pytest.mark.django_db
def test_coupon_codes_scoped_per_store() -> None:
    a = create_tenant(name="A", slug="a")
    b = create_tenant(name="B", slug="b")
    from apps.promotions import services as promo_services

    Coupon.objects.create(
        tenant=a, code="SAVE", discount_type="percentage", value=10, is_active=True
    )
    Coupon.objects.create(
        tenant=b, code="SAVE", discount_type="percentage", value=50, is_active=True
    )
    assert promo_services.validate_code("save", tenant_id=a.id).value == 10
    assert promo_services.validate_code("SAVE", tenant_id=b.id).value == 50


@pytest.mark.django_db
def test_store_setting_overrides_global() -> None:
    a = create_tenant(name="A", slug="a")
    config_services.set_setting("store.tagline", "Global line")
    assert selectors.get_setting("store.tagline", tenant=a) == "Global line"
    config_services.set_setting("store.tagline", "A line", tenant=a)
    assert selectors.get_setting("store.tagline", tenant=a) == "A line"
    # Other stores still see the global value.
    b = create_tenant(name="B", slug="b")
    assert selectors.get_setting("store.tagline", tenant=b) == "Global line"


@pytest.mark.django_db
def test_effective_tenant_falls_back_to_default(rf=None) -> None:
    from django.test import RequestFactory

    from apps.tenants.services import get_or_create_default_tenant

    default = get_or_create_default_tenant()
    request = RequestFactory().get("/")
    request.tenant = None
    assert get_effective_tenant(request).id == default.id
