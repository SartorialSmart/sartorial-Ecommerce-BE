from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.tenants.models import Tenant, TenantApiKey, TenantMembership, TenantType
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


@pytest.mark.django_db
def test_seller_self_links_and_regenerates_erp_key(client: APIClient) -> None:
    seller, store = _seller_with_store("erp-self-link")
    client.force_authenticate(seller)
    headers = {"HTTP_X_TENANT_SLUG": store.slug}

    initial = client.get("/api/v1/admin/erp-link/", **headers)
    assert initial.status_code == 200
    assert initial.json()["linked"] is False

    linked = client.post(
        "/api/v1/admin/erp-link/",
        {"erp_business_id": "ERP-8842"},
        format="json",
        **headers,
    )
    assert linked.status_code == 200
    payload = linked.json()
    assert payload["linked"] is True
    assert payload["erp_business_id"] == "ERP-8842"
    assert payload["api_key"].startswith("sk_")

    store.refresh_from_db()
    assert store.type == TenantType.ERP_SUBSCRIBER
    assert store.erp_business_id == "ERP-8842"

    status = client.get("/api/v1/admin/erp-link/", **headers)
    assert status.json()["linked"] is True
    assert status.json()["api_key_prefix"] == payload["api_key"][:10]
    assert "api_key" not in status.json()

    regenerated = client.post("/api/v1/admin/erp-link/key/", {}, format="json", **headers)
    assert regenerated.status_code == 200
    assert regenerated.json()["api_key"].startswith("sk_")
    assert regenerated.json()["api_key"] != payload["api_key"]
    assert TenantApiKey.objects.filter(tenant=store, is_active=True).count() == 1


@pytest.mark.django_db
def test_seller_can_unlink_erp_store(client: APIClient) -> None:
    seller, store = _seller_with_store("erp-unlink")
    client.force_authenticate(seller)
    headers = {"HTTP_X_TENANT_SLUG": store.slug}
    client.post("/api/v1/admin/erp-link/", {"erp_seller_id": "SELLER-42"}, format="json", **headers)

    response = client.delete("/api/v1/admin/erp-link/", **headers)
    assert response.status_code == 200
    store.refresh_from_db()
    assert store.type == TenantType.INDEPENDENT
    assert store.erp_business_id is None
    assert TenantApiKey.objects.filter(tenant=store, is_active=True).count() == 0


@pytest.mark.django_db
def test_erp_business_id_cannot_be_linked_twice(client: APIClient) -> None:
    seller, store = _seller_with_store("erp-dupe")
    other = create_tenant(name="Other", slug="erp-dupe-other")
    other.type = TenantType.ERP_SUBSCRIBER
    other.erp_business_id = "ERP-DUP"
    other.save(update_fields=["type", "erp_business_id", "updated_at"])
    client.force_authenticate(seller)

    response = client.post(
        "/api/v1/admin/erp-link/",
        {"erp_business_id": "ERP-DUP"},
        format="json",
        HTTP_X_TENANT_SLUG=store.slug,
    )
    assert response.status_code == 400
