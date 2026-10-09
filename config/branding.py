"""Single source of truth for product branding.

Phase 1 (technical report §13): all strings that carry the product name live
here so a rename touches one place. Environment variables still win at runtime
where they exist — these constants are the *defaults* used when no env var is
set, plus the values baked into migrations-agnostic defaults (store settings,
test fixtures, health checks).

Product: SartorialEcommerce — multi-tenant commerce backend serving
Sartorial ERP subscribers (ERP is source of truth) and independent sellers
(marketplace-native). Shared-DB tenancy: every tenant is an isolated store
scoped by ``tenant_id`` (see ``apps.tenants``).
"""

from __future__ import annotations

PRODUCT_NAME = "SartorialEcommerce"
PRODUCT_SLUG = "sartorialecommerce"
PACKAGE_NAME = "sartorialecommerce-backend"
SERVICE_ID = "sartorialecommerce-backend"
CELERY_APP_NAME = "sartorialecommerce"

API_TITLE = "SartorialEcommerce API"
API_DESCRIPTION = (
    "Multi-tenant e-commerce backend for Sartorial ERP subscribers "
    "and independent sellers: isolated stores, shared catalogue engine, "
    "server-side basket, reservations, multi-currency pricing, payments, "
    "deliveries and ERP publication link."
)
API_VERSION = "0.2.0"

# Dev/test defaults (prod values come from env — see .env.example).
DEFAULT_DB_NAME = "sartorialecommerce"
DEFAULT_DB_USER = "sartorialecommerce"
DEFAULT_DB_PASSWORD = "sartorialecommerce"
DEFAULT_EMAIL_DOMAIN = "sartorialecommerce.test"
DEFAULT_FROM_EMAIL = f"no-reply@{DEFAULT_EMAIL_DOMAIN}"
DEFAULT_SUPPORT_EMAIL = f"support@{DEFAULT_EMAIL_DOMAIN}"
DEFAULT_FROM_NAME = PRODUCT_NAME

DEFAULT_UPLOAD_FOLDER = f"{PRODUCT_SLUG}/products"
CACHE_LOCAL_LOCATION = f"{PRODUCT_SLUG}-local"

DEFAULT_STORE_NAME = PRODUCT_NAME
DEFAULT_STORE_TAGLINE = "Fashion commerce for Sartorial businesses."
DEFAULT_SUPPORT_EMAIL_SETTING = DEFAULT_SUPPORT_EMAIL

# Code default for currency. The suite's fixtures and 17 cross-app tests are
# built around a USD base (USD:1, EUR:0.92, NGN:1500), so the code default
# stays USD to keep the build green. Nigerian stores set ``currency.base=NGN``
# (and add NGN to ``currency.enabled``) as a storeconfig setting at
# provisioning/launch — no code release needed. Phase 3 scopes these settings
# per tenant so each store carries its own base currency.
DEFAULT_BASE_CURRENCY = "USD"
DEFAULT_ENABLED_CURRENCIES: list[str] = ["USD", "EUR", "GBP"]
