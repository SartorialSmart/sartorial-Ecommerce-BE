"""Store onboarding: any authenticated user can claim their own store."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.accounts.tests.factories import UserFactory
from apps.storeconfig import selectors
from apps.tenants.models import Tenant, TenantMembership

SETUP_URL = "/api/v1/admin/stores/setup/"


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.mark.django_db
def test_setup_requires_authentication(client: APIClient) -> None:
    resp = client.post(SETUP_URL, {"name": "X"}, format="json")
    assert resp.status_code in (401, 403)


@pytest.mark.django_db
def test_setup_requires_name(client: APIClient) -> None:
    user = UserFactory(role=Role.CUSTOMER, password="Pass12345!")
    client.force_authenticate(user)
    resp = client.post(SETUP_URL, {}, format="json")
    assert resp.status_code == 400
    assert "name" in resp.data


@pytest.mark.django_db
def test_customer_setup_creates_store_and_promotes_to_seller(client: APIClient) -> None:
    user = UserFactory(role=Role.CUSTOMER, password="Pass12345!")
    client.force_authenticate(user)
    resp = client.post(
        SETUP_URL,
        {
            "name": "Kente House",
            "slug": "kente-house",
            "tagline": "Woven well.",
            "plan": "asooke",
            "city": "Accra, Ghana",
            "currency": "GHS",
        },
        format="json",
    )
    assert resp.status_code == 201
    tenant = Tenant.objects.get(slug="kente-house")

    user.refresh_from_db()
    assert user.role == Role.SELLER
    membership = TenantMembership.objects.get(tenant=tenant, user=user)
    assert membership.role == "owner"

    assert selectors.get_setting("store.name", tenant=tenant) == "Kente House"
    assert selectors.get_setting("store.tagline", tenant=tenant) == "Woven well."
    assert selectors.get_setting("store.plan", tenant=tenant) == "asooke"
    assert selectors.get_setting("store.domain", tenant=tenant) == "kente-house"
    assert selectors.get_setting("store.setup_complete", tenant=tenant) is True


@pytest.mark.django_db
def test_setup_is_idempotent_for_existing_store(client: APIClient) -> None:
    user = UserFactory(role=Role.CUSTOMER, password="Pass12345!")
    client.force_authenticate(user)
    first = client.post(SETUP_URL, {"name": "First Store"}, format="json")
    assert first.status_code == 201
    second = client.post(SETUP_URL, {"name": "Renamed Store"}, format="json")
    assert second.status_code == 200

    assert Tenant.objects.filter(memberships__user=user).count() == 1
    tenant = Tenant.objects.get(memberships__user=user)
    assert tenant.name == "Renamed Store"
    assert selectors.get_setting("store.name", tenant=tenant) == "Renamed Store"


@pytest.mark.django_db
def test_setup_generates_unique_slug_on_collision(client: APIClient) -> None:
    user_a = UserFactory(role=Role.CUSTOMER, password="Pass12345!")
    user_b = UserFactory(role=Role.CUSTOMER, password="Pass12345!")
    client.force_authenticate(user_a)
    assert (
        client.post(SETUP_URL, {"name": "Shared", "slug": "shared"}, format="json").status_code
        == 201
    )
    client.force_authenticate(user_b)
    resp = client.post(SETUP_URL, {"name": "Shared", "slug": "shared"}, format="json")
    assert resp.status_code == 201
    assert resp.data["slug"] == "shared-2"
