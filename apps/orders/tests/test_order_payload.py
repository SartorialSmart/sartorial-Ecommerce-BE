"""The order payload must expose every item bought — image, options, prices —
so the admin (and customer) can see the full order detail."""

from __future__ import annotations

import pytest

from apps.cart import services as cart_services
from apps.cart.tests.factories import make_variant, setup_currencies
from apps.catalog.models import ProductImage
from apps.orders import services as order_services
from apps.orders.serializers import OrderSerializer
from apps.payments import services as payment_services
from apps.storeconfig import services as config_services


@pytest.fixture
def setup(db) -> None:
    setup_currencies()
    config_services.set_setting("currency.fx_markup_percent", "0")


@pytest.mark.django_db
def test_order_payload_includes_items_image_and_prices(setup) -> None:
    v = make_variant("5000.00", title="Detailed Tee")
    ProductImage.objects.create(
        product=v.product, public_id="orders/tee-primary", is_primary=True
    )

    cart = cart_services.get_or_create_cart(session_key="detail")
    cart_services.add_item(cart, variant_id=str(v.id), quantity=3)
    cart_services.set_shipping(cart, {"name": "A", "line1": "1 St", "city": "T", "country": "US"})
    order = order_services.checkout(cart, idempotency_key="detail-1", currency="USD")
    payment_services.confirm_mock_payment(order.payments.first())
    order.refresh_from_db()

    data = OrderSerializer(order).data
    assert len(data["lines"]) == 1
    line = data["lines"][0]

    # Every detail the admin needs to see what was bought.
    assert line["title"] == "Detailed Tee"
    assert line["sku"]
    assert line["quantity"] == 3
    assert line["image"] and "tee-primary" in line["image"]
    assert line["unit_price_charged"] and line["line_total_charged"]
    assert line["product_deleted"] is False
