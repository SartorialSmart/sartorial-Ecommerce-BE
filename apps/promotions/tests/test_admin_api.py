from __future__ import annotations

from decimal import Decimal
from typing import Any, cast

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.accounts.tests.factories import UserFactory
from apps.catalog.models import Category
from apps.promotions.models import Coupon
from apps.tenants.models import TenantMembership
from apps.tenants.services import create_tenant

COUPONS_URL = "/api/v1/admin/promotions/coupons/"


@pytest.fixture
def client() -> APIClient:
    return APIClient()


def _seller_with_store(*, slug: str) -> tuple[Any, Any]:
    seller = cast(User, UserFactory(role=Role.SELLER, password="Pass12345!"))  # type: ignore[no-untyped-call]
    store = create_tenant(name=slug.title(), slug=slug)
    TenantMembership.objects.create(tenant=store, user=seller, role="owner")
    return seller, store


def _coupon(*, code: str, tenant: Any | None = None) -> Coupon:
    return Coupon.objects.create(
        code=code,
        description=code,
        discount_type=Coupon.DiscountType.PERCENTAGE,
        value=Decimal("10"),
        tenant=tenant,
    )


@pytest.mark.django_db
def test_coupon_admin_rejects_customers(client: APIClient) -> None:
    assert client.get(COUPONS_URL).status_code in (401, 403)
    client.force_authenticate(
        cast(User, UserFactory(role=Role.CUSTOMER, password="x"))  # type: ignore[no-untyped-call]
    )
    assert client.get(COUPONS_URL).status_code == 403


@pytest.mark.django_db
def test_seller_lists_and_creates_coupons_for_own_store(client: APIClient) -> None:
    seller, store = _seller_with_store(slug="couture-hq")
    other = create_tenant(name="Other", slug="other-store")
    mine = _coupon(code="MINE10", tenant=store)
    theirs = _coupon(code="THEIRS10", tenant=other)
    client.force_authenticate(seller)

    listed = client.get(COUPONS_URL)
    assert listed.status_code == 200
    codes = [row["code"] for row in listed.data["results"]]
    assert "MINE10" in codes
    assert "THEIRS10" not in codes

    created = client.post(
        COUPONS_URL,
        {
            "code": "NEW10",
            "description": "New coupon",
            "discount_type": Coupon.DiscountType.PERCENTAGE,
            "value": "10.00",
        },
        format="json",
        HTTP_X_TENANT_SLUG=store.slug,
    )
    assert created.status_code == 201
    assert Coupon.objects.get(code="NEW10").tenant_id == store.id
    assert Coupon.objects.get(id=mine.id).tenant_id == store.id
    assert Coupon.objects.get(id=theirs.id).tenant_id == other.id


@pytest.mark.django_db
def test_seller_cannot_use_foreign_category(client: APIClient) -> None:
    seller, store = _seller_with_store(slug="sartorial-hq")
    other = create_tenant(name="Other", slug="other-store")
    foreign_category = Category.objects.create(name="Foreign", slug="foreign", tenant=other)
    client.force_authenticate(seller)

    response = client.post(
        COUPONS_URL,
        {
            "code": "FOREIGN10",
            "discount_type": Coupon.DiscountType.PERCENTAGE,
            "value": "10.00",
            "category": str(foreign_category.id),
        },
        format="json",
        HTTP_X_TENANT_SLUG=store.slug,
    )
    assert response.status_code == 403
    assert not Coupon.objects.filter(code="FOREIGN10").exists()
