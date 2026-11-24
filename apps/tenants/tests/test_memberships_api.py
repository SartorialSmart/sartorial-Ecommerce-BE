"""Memberships API: sellers read their own rows; owners/managers can invite."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.accounts.tests.factories import UserFactory
from apps.tenants.models import TenantMembership
from apps.tenants.services import create_tenant

MEMBERSHIPS_URL = "/api/v1/admin/tenant-memberships/"


@pytest.fixture
def client() -> APIClient:
    return APIClient()


def _seller_with_store(slug: str):
    seller = UserFactory(role=Role.SELLER, password="Pass12345!")
    store = create_tenant(name=slug.replace("-", " ").title(), slug=slug)
    TenantMembership.objects.create(tenant=store, user=seller, role="owner")
    return seller, store


def _rows(resp) -> list:
    data = resp.data
    return data.get("results", data) if isinstance(data, dict) else data


@pytest.mark.django_db
def test_seller_lists_only_their_own_memberships(client: APIClient) -> None:
    seller, store = _seller_with_store("mine-store")
    other = create_tenant(name="Other", slug="other-store")
    stranger = UserFactory(role=Role.SELLER, password="Pass12345!")
    TenantMembership.objects.create(tenant=other, user=stranger, role="owner")

    client.force_authenticate(seller)
    resp = client.get(MEMBERSHIPS_URL)
    assert resp.status_code == 200
    rows = _rows(resp)
    assert len(rows) == 1
    assert str(rows[0]["tenant"]) == str(store.id)
    assert rows[0]["user_email"] == seller.email
    assert rows[0]["user_name"] == seller.full_name
    assert rows[0]["role"] == "owner"


@pytest.mark.django_db
def test_admin_sees_all_memberships(client: APIClient) -> None:
    admin = UserFactory(role=Role.ADMIN, password="x")
    _seller_with_store("mine-store")
    other = create_tenant(name="Other", slug="other-store")
    stranger = UserFactory(role=Role.SELLER, password="Pass12345!")
    TenantMembership.objects.create(tenant=other, user=stranger, role="owner")

    client.force_authenticate(admin)
    resp = client.get(MEMBERSHIPS_URL)
    assert resp.status_code == 200
    assert len(_rows(resp)) == 2


@pytest.mark.django_db
def test_store_owner_can_invite_a_member(client: APIClient) -> None:
    owner, store = _seller_with_store("mine-store")
    invitee = UserFactory(role=Role.CUSTOMER, password="Pass12345!")

    client.force_authenticate(owner)
    resp = client.post(
        f"/api/v1/admin/tenants/{store.slug}/members/",
        {"email": invitee.email, "role": "staff"},
        format="json",
    )
    assert resp.status_code == 201
    assert TenantMembership.objects.filter(tenant=store, user=invitee, role="staff").exists()


@pytest.mark.django_db
def test_non_member_cannot_invite(client: APIClient) -> None:
    _, store = _seller_with_store("mine-store")
    stranger = UserFactory(role=Role.SELLER, password="Pass12345!")
    invitee = UserFactory(role=Role.CUSTOMER, password="Pass12345!")

    client.force_authenticate(stranger)
    resp = client.post(
        f"/api/v1/admin/tenants/{store.slug}/members/",
        {"email": invitee.email},
        format="json",
    )
    assert resp.status_code == 403
    assert not TenantMembership.objects.filter(tenant=store, user=invitee).exists()


@pytest.mark.django_db
def test_invite_unknown_user_returns_404(client: APIClient) -> None:
    owner, store = _seller_with_store("mine-store")
    client.force_authenticate(owner)
    resp = client.post(
        f"/api/v1/admin/tenants/{store.slug}/members/",
        {"email": "ghost@example.com"},
        format="json",
    )
    assert resp.status_code == 404


@pytest.mark.django_db
def test_invite_rejects_unknown_role(client: APIClient) -> None:
    owner, store = _seller_with_store("mine-store")
    invitee = UserFactory(role=Role.CUSTOMER, password="Pass12345!")
    client.force_authenticate(owner)
    resp = client.post(
        f"/api/v1/admin/tenants/{store.slug}/members/",
        {"email": invitee.email, "role": "wizard"},
        format="json",
    )
    assert resp.status_code == 400
    assert "role" in resp.data
