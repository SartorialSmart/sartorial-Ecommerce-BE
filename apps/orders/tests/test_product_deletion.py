"""Deleting a product that has orders must succeed and keep order history."""

from __future__ import annotations

import pytest

from apps.cart import services as cart_services
from apps.cart.tests.factories import make_variant, setup_currencies
from apps.catalog.models import Product
from apps.orders import services as order_services
from apps.payments import services as payment_services
from apps.storeconfig import services as config_services


@pytest.fixture
def setup(db) -> None:
    setup_currencies()
    config_services.set_setting("currency.fx_markup_percent", "0")


@pytest.mark.django_db
def test_ordered_product_can_be_deleted_and_line_preserved(setup) -> None:
    v = make_variant("5000.00", title="Deletable Tee")
    product_id = v.product_id

    cart = cart_services.get_or_create_cart(session_key="del")
    cart_services.add_item(cart, variant_id=str(v.id), quantity=2)
    cart_services.set_shipping(cart, {"name": "A", "line1": "1 St", "city": "T", "country": "US"})
    order = order_services.checkout(cart, idempotency_key="del-1", currency="USD")
    payment_services.confirm_mock_payment(order.payments.first())

    line = order.lines.get()
    assert line.variant_id == v.id
    assert line.sku and line.title  # snapshot captured at checkout

    # The product was ordered — but SET_NULL means it can still be deleted.
    Product.objects.get(id=product_id).delete()

    assert not Product.objects.filter(id=product_id).exists()
    line.refresh_from_db()
    assert line.variant_id is None  # link cleared, not blocked
    assert line.title == "Deletable Tee"  # history preserved via the snapshot
    assert line.quantity == 2
    assert line.line_total_charged > 0
