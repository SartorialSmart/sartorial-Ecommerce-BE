from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from apps.common.models import AuditLog
from apps.storeconfig import selectors, services
from apps.storeconfig.models import Setting


@pytest.mark.django_db
def test_get_setting_returns_spec_default_when_unset() -> None:
    from config.branding import (
        DEFAULT_BASE_CURRENCY,
        DEFAULT_ENABLED_CURRENCIES,
        DEFAULT_STORE_NAME,
    )

    assert selectors.get_setting("store.name") == DEFAULT_STORE_NAME
    assert selectors.get_setting("currency.base") == DEFAULT_BASE_CURRENCY
    assert selectors.get_setting("currency.enabled") == DEFAULT_ENABLED_CURRENCIES


@pytest.mark.django_db
def test_unknown_key_raises() -> None:
    with pytest.raises(ValidationError):
        selectors.get_setting("does.not.exist")


@pytest.mark.django_db
def test_set_setting_overrides_default_and_persists() -> None:
    services.set_setting("store.name", "Acme")
    assert selectors.get_setting("store.name") == "Acme"
    assert Setting.objects.filter(key="store.name").exists()


@pytest.mark.django_db
def test_set_setting_coerces_types() -> None:
    services.set_setting("currency.refresh_minutes", "90")
    assert selectors.get_setting("currency.refresh_minutes") == 90

    services.set_setting("features.guest_payers", "false")
    assert selectors.get_setting("features.guest_payers") is False


@pytest.mark.django_db
def test_invalid_value_rejected() -> None:
    with pytest.raises(ValidationError):
        services.set_setting("currency.base", "DOLLARS")  # not 3 letters
    with pytest.raises(ValidationError):
        services.set_setting("currency.fx_markup_percent", "-5")  # negative


@pytest.mark.django_db
def test_set_setting_writes_audit_entry() -> None:
    services.set_setting("store.name", "Audited")
    entry = AuditLog.objects.get(target_type="storeconfig.Setting", target_id="store.name")
    assert entry.action == AuditLog.Action.CREATE
    assert entry.changes["store.name"]["after"] == "Audited"


@pytest.mark.django_db
def test_reset_setting_falls_back_to_default() -> None:
    from config.branding import DEFAULT_STORE_NAME

    services.set_setting("store.name", "Temp")
    services.reset_setting("store.name")
    assert selectors.get_setting("store.name") == DEFAULT_STORE_NAME
    assert not Setting.objects.filter(key="store.name").exists()


@pytest.mark.django_db
def test_set_many_is_atomic() -> None:
    with pytest.raises(ValidationError):
        services.set_many({"store.name": "Ok", "currency.base": "XX"})
    # The valid key must not have been written because validation failed first.
    assert not Setting.objects.filter(key="store.name").exists()


@pytest.mark.django_db
def test_social_links_validation_and_public_exposure() -> None:
    from apps.storeconfig.schema import PUBLIC_KEYS

    # Exposed to the storefront.
    assert "footer.social_links" in PUBLIC_KEYS

    # Valid list is accepted and persisted.
    services.set_setting(
        "footer.social_links",
        [{"name": "Instagram", "url": "https://instagram.com/me", "icon": "instagram"}],
    )
    links = selectors.get_setting("footer.social_links")
    assert links[0]["name"] == "Instagram"

    # A bad URL is rejected.
    with pytest.raises(ValidationError):
        services.set_setting(
            "footer.social_links", [{"name": "X", "url": "not-a-url", "icon": "x"}]
        )
    # A missing name is rejected.
    with pytest.raises(ValidationError):
        services.set_setting(
            "footer.social_links", [{"name": "", "url": "https://x.com", "icon": "x"}]
        )
