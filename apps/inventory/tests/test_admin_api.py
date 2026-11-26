from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.accounts.tests.factories import UserFactory
from apps.catalog.models import Product, Variant
from apps.common.models import AuditLog
from apps.inventory.services import available_quantity
from apps.tenants.models import TenantMembership
from apps.tenants.services import create_tenant


@pytest.fixture
def client() -> APIClient:
    return APIClient()


def _variant() -> Variant:
    p = Product.objects.create(title="P")
    return Variant.objects.create(product=p, sku="SET-1", price=Decimal("5"), is_default=True)


def _seller_with_store(*, slug: str) -> tuple[Any, Any]:
    seller = UserFactory(role=Role.SELLER, password="Pass12345!")
    store = create_tenant(name=slug.title(), slug=slug)
    TenantMembership.objects.create(tenant=store, user=seller, role="owner")
    return seller, store


def _tenant_variant(store: Any, sku: str) -> Variant:
    product = Product.objects.create(title=sku, tenant=store)
    return Variant.objects.create(product=product, sku=sku, price=Decimal("5"), is_default=True)


@pytest.mark.django_db
def test_stock_admin_requires_admin(client: APIClient) -> None:
    assert client.get("/api/v1/admin/inventory/stock/").status_code in (401, 403)
    client.force_authenticate(UserFactory(role=Role.CUSTOMER, password="x"))
    assert client.get("/api/v1/admin/inventory/stock/").status_code == 403


@pytest.mark.django_db
def test_admin_sets_stock_and_audits(client: APIClient) -> None:
    admin = UserFactory(role=Role.ADMIN, password="x")
    client.force_authenticate(admin)
    v = _variant()
    resp = client.post(
        "/api/v1/admin/inventory/stock/", {"variant": str(v.id), "quantity": 42}, format="json"
    )
    assert resp.status_code == 200
    assert available_quantity(v) == 42
    assert AuditLog.objects.filter(target_type="inventory.StockItem").exists()


@pytest.mark.django_db
def test_seller_sets_and_lists_only_own_stock(client: APIClient) -> None:
    seller, store = _seller_with_store(slug="seller-stock")
    other = create_tenant(name="Other", slug="other-stock")
    mine = _tenant_variant(store, "MINE-1")
    _tenant_variant(other, "THEIRS-1")

    client.force_authenticate(seller)
    resp = client.post(
        "/api/v1/admin/inventory/stock/",
        {"variant": str(mine.id), "quantity": 4},
        format="json",
        HTTP_X_TENANT_SLUG=store.slug,
    )
    assert resp.status_code == 200

    listed = client.get(
        "/api/v1/admin/inventory/stock/?low_stock=true",
        HTTP_X_TENANT_SLUG=store.slug,
    )
    assert listed.status_code == 200
    skus = [row["sku"] for row in listed.json()]
    assert "MINE-1" in skus
    assert "THEIRS-1" not in skus

    denied = client.get(
        "/api/v1/admin/inventory/stock/",
        HTTP_X_TENANT_SLUG=other.slug,
    )
    assert denied.status_code == 403


@pytest.mark.django_db
def test_seller_cannot_set_stock_for_foreign_variant(client: APIClient) -> None:
    seller, store = _seller_with_store(slug="seller-stock")
    other = create_tenant(name="Other", slug="other-stock")
    theirs = _tenant_variant(other, "THEIRS-2")

    client.force_authenticate(seller)
    resp = client.post(
        "/api/v1/admin/inventory/stock/",
        {"variant": str(theirs.id), "quantity": 10},
        format="json",
        HTTP_X_TENANT_SLUG=store.slug,
    )
    assert resp.status_code == 403
