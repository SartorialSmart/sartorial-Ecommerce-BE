"""Seller-scoped access to the catalog admin API.

Sellers (role=seller) manage their own store(s)' catalogue; platform admins keep
full access. Every seller path must be restricted to the stores the seller
belongs to — including write targets, never trusting a client-supplied tenant.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.accounts.tests.factories import UserFactory
from apps.catalog.models import Product
from apps.tenants.models import TenantMembership
from apps.tenants.services import create_tenant


@pytest.fixture
def client() -> APIClient:
    return APIClient()


def _seller_with_store(*, slug: str) -> tuple:
    seller = UserFactory(role=Role.SELLER, password="Pass12345!")
    store = create_tenant(name=slug.title(), slug=slug)
    TenantMembership.objects.create(tenant=store, user=seller, role="owner")
    return seller, store


@pytest.mark.django_db
def test_seller_can_create_product_in_own_store(client: APIClient) -> None:
    seller, store = _seller_with_store(slug="adaeze-test")
    create_tenant(name="Other", slug="other-test")

    client.force_authenticate(seller)
    resp = client.post(
        "/api/v1/admin/catalog/products/create-full/",
        {
            "kind": "simple",
            "title": "Handwoven scarf",
            "sku": "HF-001",
            "price": "15000.00",
            "stock": 7,
        },
        format="json",
        HTTP_X_TENANT_SLUG="adaeze-test",
    )
    assert resp.status_code == 201
    product = Product.objects.get(title="Handwoven scarf")
    assert product.tenant_id == store.id


@pytest.mark.django_db
def test_seller_cannot_write_into_a_foreign_store(client: APIClient) -> None:
    seller, _ = _seller_with_store(slug="adaeze-test")
    create_tenant(name="Other", slug="other-test")

    client.force_authenticate(seller)
    resp = client.post(
        "/api/v1/admin/catalog/products/create-full/",
        {
            "kind": "simple",
            "title": "Sneaky product",
            "sku": "SN-001",
            "price": "100.00",
            "stock": 1,
        },
        format="json",
        HTTP_X_TENANT_SLUG="other-test",
    )
    assert resp.status_code == 403
    assert not Product.objects.filter(title="Sneaky product").exists()


@pytest.mark.django_db
def test_seller_singleton_membership_is_auto_assigned(client: APIClient) -> None:
    seller, store = _seller_with_store(slug="adaeze-test")

    client.force_authenticate(seller)
    resp = client.post(
        "/api/v1/admin/catalog/products/create-full/",
        {
            "kind": "simple",
            "title": "Auto-assigned product",
            "sku": "AA-001",
            "price": "100.00",
            "stock": 1,
        },
        format="json",
    )
    assert resp.status_code == 201
    assert Product.objects.get(title="Auto-assigned product").tenant_id == store.id


@pytest.mark.django_db
def test_seller_product_list_excludes_foreign_stores(client: APIClient) -> None:
    from apps.catalog.tests.factories import ProductFactory

    seller, store = _seller_with_store(slug="adaeze-test")
    other = create_tenant(name="Other", slug="other-test")
    ProductFactory(title="Mine", tenant=store)
    ProductFactory(title="Theirs", tenant=other)

    client.force_authenticate(seller)
    resp = client.get("/api/v1/admin/catalog/products/", HTTP_X_TENANT_SLUG="adaeze-test")
    assert resp.status_code == 200
    titles = [row["title"] for row in resp.data["results"]]
    assert titles == ["Mine"]


@pytest.mark.django_db
def test_customer_role_is_rejected(client: APIClient) -> None:
    customer = UserFactory(role=Role.CUSTOMER, password="Pass12345!")
    client.force_authenticate(customer)
    assert client.get("/api/v1/admin/catalog/products/").status_code == 403
    resp = client.post(
        "/api/v1/admin/catalog/products/create-full/",
        {"kind": "simple", "title": "Nope", "sku": "NP-001", "price": "1.00", "stock": 0},
        format="json",
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_my_stores_returns_only_own_memberships(client: APIClient) -> None:
    seller, _ = _seller_with_store(slug="adaeze-test")
    create_tenant(name="Other", slug="other-test")

    client.force_authenticate(seller)
    resp = client.get("/api/v1/admin/my-stores/")
    assert resp.status_code == 200
    results = resp.data["results"] if isinstance(resp.data, dict) else resp.data
    assert [row["slug"] for row in results] == ["adaeze-test"]


@pytest.mark.django_db
def test_seller_cannot_create_option_type_on_foreign_product(client: APIClient) -> None:
    from apps.catalog.tests.factories import ProductFactory

    seller, _ = _seller_with_store(slug="adaeze-test")
    other = create_tenant(name="Other", slug="other-test")
    foreign = ProductFactory(title="Theirs", tenant=other)

    client.force_authenticate(seller)
    resp = client.post(
        "/api/v1/admin/catalog/option-types/",
        {"product": foreign.id, "name": "Size", "position": 0},
        format="json",
        HTTP_X_TENANT_SLUG="adaeze-test",
    )
    assert resp.status_code == 403
    assert not foreign.option_types.exists()


@pytest.mark.django_db
def test_seller_cannot_create_variant_on_foreign_product(client: APIClient) -> None:
    from apps.catalog.tests.factories import ProductFactory

    seller, _ = _seller_with_store(slug="adaeze-test")
    other = create_tenant(name="Other", slug="other-test")
    foreign = ProductFactory(title="Theirs", tenant=other)

    client.force_authenticate(seller)
    resp = client.post(
        "/api/v1/admin/catalog/variants/",
        {"product": foreign.id, "sku": "FK-001", "price": "10.00"},
        format="json",
        HTTP_X_TENANT_SLUG="adaeze-test",
    )
    assert resp.status_code == 403
    assert not foreign.variants.exists()


@pytest.mark.django_db
def test_seller_cannot_repoint_product_category_to_foreign_store(client: APIClient) -> None:
    from apps.catalog.tests.factories import CategoryFactory, ProductFactory

    seller, store = _seller_with_store(slug="adaeze-test")
    mine = ProductFactory(title="Mine", tenant=store)
    other = create_tenant(name="Other", slug="other-test")
    foreign_category = CategoryFactory(name="Foreign", slug="foreign", tenant=other)

    client.force_authenticate(seller)
    resp = client.patch(
        f"/api/v1/admin/catalog/products/{mine.id}/",
        {"category": foreign_category.id},
        format="json",
        HTTP_X_TENANT_SLUG="adaeze-test",
    )
    assert resp.status_code == 403
    mine.refresh_from_db()
    assert mine.category_id != foreign_category.id


@pytest.mark.django_db
def test_seller_cannot_attach_option_value_to_foreign_option_type(client: APIClient) -> None:
    from apps.catalog.models import OptionType
    from apps.catalog.tests.factories import ProductFactory

    seller, _ = _seller_with_store(slug="adaeze-test")
    other = create_tenant(name="Other", slug="other-test")
    foreign = ProductFactory(title="Theirs", tenant=other)
    foreign_type = OptionType.objects.create(product=foreign, name="Size", position=0)

    client.force_authenticate(seller)
    resp = client.post(
        "/api/v1/admin/catalog/option-values/",
        {"option_type": foreign_type.id, "value": "M", "position": 0},
        format="json",
        HTTP_X_TENANT_SLUG="adaeze-test",
    )
    assert resp.status_code == 403
    assert not foreign_type.values.exists()


@pytest.mark.django_db
def test_seller_cannot_repoint_image_to_foreign_variant(client: APIClient) -> None:
    from apps.catalog.models import ProductImage
    from apps.catalog.tests.factories import ProductFactory, VariantFactory

    seller, store = _seller_with_store(slug="adaeze-test")
    own_product = ProductFactory(title="Mine", tenant=store)
    image = ProductImage.objects.create(product=own_product, public_id="dem/image1")
    other = create_tenant(name="Other", slug="other-test")
    foreign_product = ProductFactory(title="Theirs", tenant=other)
    foreign_variant = VariantFactory(product=foreign_product, sku="FOR-1")

    client.force_authenticate(seller)
    resp = client.patch(
        f"/api/v1/admin/catalog/images/{image.id}/",
        {"variant": foreign_variant.id},
        format="json",
        HTTP_X_TENANT_SLUG="adaeze-test",
    )
    assert resp.status_code == 403
    image.refresh_from_db()
    assert image.variant_id is None


@pytest.mark.django_db
def test_seller_cannot_attach_image_to_foreign_variant(client: APIClient) -> None:
    from apps.catalog.tests.factories import ProductFactory, VariantFactory

    seller, store = _seller_with_store(slug="adaeze-test")
    own_product = ProductFactory(title="Mine", tenant=store)
    other = create_tenant(name="Other", slug="other-test")
    foreign_product = ProductFactory(title="Theirs", tenant=other)
    foreign_variant = VariantFactory(product=foreign_product, sku="FOR-2")

    client.force_authenticate(seller)
    resp = client.post(
        f"/api/v1/admin/catalog/products/{own_product.id}/images/",
        {"public_id": "dem/image2", "variant": foreign_variant.id},
        format="json",
        HTTP_X_TENANT_SLUG="adaeze-test",
    )
    assert resp.status_code == 403
    assert not own_product.images.exists()


@pytest.mark.django_db
def test_multi_store_seller_without_header_cannot_create_product(client: APIClient) -> None:
    seller, _ = _seller_with_store(slug="adaeze-test")
    second = create_tenant(name="Second", slug="second-test")
    TenantMembership.objects.create(tenant=second, user=seller, role="staff")

    client.force_authenticate(seller)
    resp = client.post(
        "/api/v1/admin/catalog/products/create-full/",
        {"kind": "simple", "title": "Ambiguous", "sku": "AM-001", "price": "10.00", "stock": 1},
        format="json",
    )
    assert resp.status_code == 400
    assert not Product.objects.filter(title="Ambiguous").exists()


@pytest.mark.django_db
def test_admin_can_write_into_any_store(client: APIClient) -> None:
    admin = UserFactory(role=Role.ADMIN, password="Pass12345!")
    other = create_tenant(name="Other", slug="other-test")
    from apps.catalog.tests.factories import ProductFactory

    foreign = ProductFactory(title="Theirs", tenant=other)

    client.force_authenticate(admin)
    resp = client.post(
        "/api/v1/admin/catalog/option-types/",
        {"product": foreign.id, "name": "Color", "position": 0},
        format="json",
    )
    assert resp.status_code == 201


@pytest.mark.django_db
def test_admin_create_full_without_tenant_still_works(client: APIClient) -> None:
    admin = UserFactory(role=Role.ADMIN, password="Pass12345!")
    client.force_authenticate(admin)
    resp = client.post(
        "/api/v1/admin/catalog/products/create-full/",
        {
            "kind": "simple",
            "title": "Admin product",
            "sku": "AD-001",
            "price": "100.00",
            "stock": 1,
        },
        format="json",
    )
    assert resp.status_code == 201
