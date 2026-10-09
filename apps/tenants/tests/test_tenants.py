from __future__ import annotations

import pytest
from django.db import IntegrityError
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.accounts.tests.factories import UserFactory
from apps.tenants.middleware import resolve_tenant
from apps.tenants.models import Tenant, TenantMembership, TenantStatus, TenantType
from apps.tenants.services import (
    add_member,
    authenticate_service_key,
    create_tenant,
    get_or_create_default_tenant,
    issue_api_key,
)


@pytest.mark.django_db
def test_create_tenant_defaults() -> None:
    tenant = create_tenant(name="Ada's Store", slug="Adas-Store")
    assert tenant.slug == "adas-store"
    assert tenant.type == TenantType.INDEPENDENT
    assert tenant.status == TenantStatus.ACTIVE
    assert tenant.is_active is True
    assert tenant.is_erp_managed is False


@pytest.mark.django_db
def test_erp_business_id_unique() -> None:
    create_tenant(name="A", slug="a", type=TenantType.ERP_SUBSCRIBER, erp_business_id="ERP-1")
    with pytest.raises(IntegrityError):
        create_tenant(name="B", slug="b", type=TenantType.ERP_SUBSCRIBER, erp_business_id="ERP-1")


@pytest.mark.django_db
def test_membership_unique_per_tenant() -> None:
    tenant = create_tenant(name="A", slug="a")
    user = UserFactory()
    add_member(tenant=tenant, email=user.email, role="owner")
    with pytest.raises(IntegrityError):
        TenantMembership.objects.create(tenant=tenant, user=user)


@pytest.mark.django_db
def test_api_key_roundtrip_and_prefix_scoping() -> None:
    tenant = create_tenant(name="A", slug="a")
    key_obj, raw = issue_api_key(tenant=tenant, name="erp-prod")
    assert raw.startswith("sk_")
    assert key_obj.prefix == raw[:10]
    # Hash stored, raw never persisted.
    assert key_obj.key_hash != raw
    authed = authenticate_service_key(raw)
    assert authed is not None
    assert authed.tenant_id == tenant.id
    assert authenticate_service_key("sk_bogus") is None


@pytest.mark.django_db
def test_resolve_tenant_by_slug_case_insensitive() -> None:
    create_tenant(name="A", slug="ada-store")
    assert resolve_tenant(slug="ADA-STORE") is not None
    assert resolve_tenant(slug="missing") is None


@pytest.mark.django_db
def test_default_tenant_bootstrap_idempotent() -> None:
    first = get_or_create_default_tenant()
    second = get_or_create_default_tenant()
    assert first.id == second.id
    assert first.slug == "default"


@pytest.mark.django_db
def test_public_store_lookup() -> None:
    create_tenant(name="Ada", slug="ada")
    client = APIClient()
    resp = client.get("/api/v1/tenants/stores/lookup/", {"slug": "ada"})
    assert resp.status_code == 200
    assert resp.data["slug"] == "ada"


@pytest.mark.django_db
def test_admin_can_create_tenant() -> None:
    admin = UserFactory(role=Role.ADMIN, password="Pass12345!")
    client = APIClient()
    client.force_authenticate(admin)
    resp = client.post(
        "/api/v1/admin/tenants/",
        {"name": "New Store", "slug": "new-store", "type": "independent"},
        format="json",
    )
    assert resp.status_code == 201
    assert Tenant.objects.filter(slug="new-store").exists()


@pytest.mark.django_db
def test_non_admin_cannot_create_tenant() -> None:
    user = UserFactory(password="Pass12345!")
    client = APIClient()
    client.force_authenticate(user)
    resp = client.post(
        "/api/v1/admin/tenants/",
        {"name": "X", "slug": "x"},
        format="json",
    )
    assert resp.status_code == 403
