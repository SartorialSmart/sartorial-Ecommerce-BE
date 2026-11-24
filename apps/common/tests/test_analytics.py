"""Analytics is role-gated and tenant-scoped: sellers see their own stores only."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.accounts.tests.factories import UserFactory
from apps.orders.models import Order, OrderStatus
from apps.tenants.models import TenantMembership
from apps.tenants.services import create_tenant

ANALYTICS_URL = "/api/v1/admin/analytics/"


@pytest.fixture
def client() -> APIClient:
    return APIClient()


def _seller_with_store(slug: str):
    seller = UserFactory(role=Role.SELLER, password="Pass12345!")
    store = create_tenant(name=slug.replace("-", " ").title(), slug=slug)
    TenantMembership.objects.create(tenant=store, user=seller, role="owner")
    return seller, store


def _paid_order(tenant, total: str = "1000.00", owner=None) -> Order:
    return Order.objects.create(
        tenant=tenant,
        status=OrderStatus.PAID,
        base_currency="NGN",
        currency="NGN",
        total_base=total,
        owner=owner,
    )


def _rows(resp) -> list:
    data = resp.data
    return data.get("results", data) if isinstance(data, dict) else data


@pytest.mark.django_db
def test_requires_admin_or_seller(client: APIClient) -> None:
    assert client.get(ANALYTICS_URL).status_code in (401, 403)
    client.force_authenticate(UserFactory(role=Role.CUSTOMER, password="x"))
    assert client.get(ANALYTICS_URL).status_code == 403


@pytest.mark.django_db
def test_seller_sees_only_own_store_numbers(client: APIClient) -> None:
    seller, store = _seller_with_store("mine-store")
    other = create_tenant(name="Other", slug="other-store")
    _paid_order(store, "5000.00")
    _paid_order(other, "9000.00")

    client.force_authenticate(seller)
    resp = client.get(ANALYTICS_URL, HTTP_X_TENANT_SLUG="mine-store")
    assert resp.status_code == 200
    assert resp.data["kpis"]["revenue"] == "5000.00"
    assert resp.data["kpis"]["orders"] == 1


@pytest.mark.django_db
def test_seller_cannot_read_a_foreign_store(client: APIClient) -> None:
    seller, _ = _seller_with_store("mine-store")
    create_tenant(name="Other", slug="other-store")

    client.force_authenticate(seller)
    resp = client.get(ANALYTICS_URL, HTTP_X_TENANT_SLUG="other-store")
    assert resp.status_code == 403


@pytest.mark.django_db
def test_seller_without_header_scoped_to_their_stores(client: APIClient) -> None:
    seller, store = _seller_with_store("mine-store")
    other = create_tenant(name="Other", slug="other-store")
    _paid_order(store, "5000.00")
    _paid_order(other, "9000.00")

    client.force_authenticate(seller)
    resp = client.get(ANALYTICS_URL)
    assert resp.status_code == 200
    assert resp.data["kpis"]["revenue"] == "5000.00"


@pytest.mark.django_db
def test_admin_scoped_and_platform_wide(client: APIClient) -> None:
    admin = UserFactory(role=Role.ADMIN, password="x")
    store_a = create_tenant(name="A", slug="store-a")
    store_b = create_tenant(name="B", slug="store-b")
    _paid_order(store_a, "100.00")
    _paid_order(store_b, "200.00")

    client.force_authenticate(admin)
    scoped = client.get(ANALYTICS_URL, HTTP_X_TENANT_SLUG="store-a")
    assert scoped.status_code == 200
    assert scoped.data["kpis"]["revenue"] == "100.00"

    wide = client.get(ANALYTICS_URL)
    assert wide.status_code == 200
    assert wide.data["kpis"]["revenue"] == "300.00"


@pytest.mark.django_db
def test_customer_kpi_counts_only_in_scope_order_owners(client: APIClient) -> None:
    seller, store = _seller_with_store("mine-store")
    other = create_tenant(name="Other", slug="other-store")
    mine_customer = UserFactory(role=Role.CUSTOMER, password="x")
    other_customer = UserFactory(role=Role.CUSTOMER, password="x")
    _paid_order(store, owner=mine_customer)
    _paid_order(other, owner=other_customer)

    client.force_authenticate(seller)
    resp = client.get(ANALYTICS_URL, HTTP_X_TENANT_SLUG="mine-store")
    assert resp.status_code == 200
    assert resp.data["kpis"]["customers"] == 1
