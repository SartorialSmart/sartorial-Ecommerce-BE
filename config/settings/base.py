"""Base Django settings shared across environments.

Environment-specific overrides live in ``dev.py`` and ``prod.py``. Nothing here
should hardcode a secret — every sensitive or deployment-specific value is read
from the environment via :func:`env`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from config.branding import (
    API_DESCRIPTION,
    API_TITLE,
    API_VERSION,
    CACHE_LOCAL_LOCATION,
    DEFAULT_DB_NAME,
    DEFAULT_DB_PASSWORD,
    DEFAULT_DB_USER,
    DEFAULT_UPLOAD_FOLDER,
)
from config.branding import (
    DEFAULT_FROM_EMAIL as BRAND_DEFAULT_FROM_EMAIL,
)
from config.branding import (
    DEFAULT_FROM_NAME as BRAND_DEFAULT_FROM_NAME,
)
from config.branding import (
    DEFAULT_SUPPORT_EMAIL as BRAND_DEFAULT_SUPPORT_EMAIL,
)

# backend/config/settings/base.py -> backend/
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load a .env file if present (no-op in production where env is injected).
load_dotenv(BASE_DIR / ".env")


def env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)


def env_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_list(key: str, default: list[str] | None = None) -> list[str]:
    raw = os.environ.get(key)
    if not raw:
        return default or []
    return [item.strip() for item in raw.split(",") if item.strip()]


SECRET_KEY = env("DJANGO_SECRET_KEY", "insecure-dev-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", ["localhost", "127.0.0.1"])

# --- Applications -----------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "drf_spectacular",
    "corsheaders",
    "django_celery_beat",
    "cloudinary",
    "cloudinary_storage",
]

# Local domain apps. Tenants (isolated stores) is core for SartorialEcommerce.
LOCAL_APPS = [
    "apps.common",
    "apps.accounts",
    "apps.tenants",
    "apps.storeconfig",
    "apps.catalog",
    "apps.inventory",
    "apps.currency",
    "apps.promotions",
    "apps.cart",
    "apps.orders",
    "apps.invoices",
    "apps.payments",
    "apps.suppliers",
    "apps.fulfillment",
    "apps.notifications",
    "apps.blog",
    "apps.erp_link",
    "apps.pricing",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.tenants.middleware.TenantMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --- Database ---------------------------------------------------------------
# Postgres is the real backend. Resolution order:
#   1. DATABASE_URL (managed providers — Neon, Supabase, RDS, …)
#   2. discrete POSTGRES_* vars (docker-compose / VM deploys)
#   3. SQLite when USE_SQLITE=1 (quick local runs with no services)
#
# USE_SQLITE wins outright so `make run` on a laptop never accidentally points
# at a production URL that happens to be exported in the shell.

# Connection lifetime. Serverless (Vercel) reuses a warm instance for a while,
# but a pooled Neon connection held across idle periods gets reaped server-side
# and resurfaces as "connection already closed" on the next request. 0 = open
# and close per request, which is the safe default behind a connection pooler.
DB_CONN_MAX_AGE = int(env("DB_CONN_MAX_AGE", "0") or "0")
# Never let a cold DB hang until the function times out.
DB_CONNECT_TIMEOUT = int(env("DB_CONNECT_TIMEOUT", "10") or "10")


def _database_from_url(url: str) -> dict[str, Any]:
    """Build a Django DATABASES entry from a postgres:// URL.

    Query-string parameters (``sslmode``, ``channel_binding``, …) are forwarded
    to psycopg as connection options — Neon requires both, and dropping them
    turns into a TLS handshake failure at runtime rather than at deploy time.
    """
    from urllib.parse import parse_qsl, unquote, urlparse

    parsed = urlparse(url)
    options: dict[str, Any] = {
        key: value for key, value in parse_qsl(parsed.query) if value not in ("", None)
    }
    # Postgres-side statement timeout, so a pathological query can't pin a
    # serverless instance open for its whole duration budget.
    statement_timeout_ms = env("DB_STATEMENT_TIMEOUT_MS", "")
    if statement_timeout_ms:
        options["options"] = f"-c statement_timeout={statement_timeout_ms}"
    options.setdefault("connect_timeout", DB_CONNECT_TIMEOUT)

    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed.path.lstrip("/")) or "postgres",
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or "5432"),
        "CONN_MAX_AGE": DB_CONN_MAX_AGE,
        "OPTIONS": options,
        # PgBouncer in transaction-pooling mode (Neon's `-pooler` host) cannot
        # hold a server-side cursor open across statements. Django's default
        # chunked iteration would break on `.iterator()` calls.
        "DISABLE_SERVER_SIDE_CURSORS": True,
    }


DATABASE_URL = env("DATABASE_URL", "")

if env_bool("USE_SQLITE", False):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": env("SQLITE_PATH", str(BASE_DIR / "db.sqlite3")),
        }
    }
elif DATABASE_URL:
    DATABASES = {"default": _database_from_url(DATABASE_URL)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB", DEFAULT_DB_NAME),
            "USER": env("POSTGRES_USER", DEFAULT_DB_USER),
            "PASSWORD": env("POSTGRES_PASSWORD", DEFAULT_DB_PASSWORD),
            "HOST": env("POSTGRES_HOST", "localhost"),
            "PORT": env("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": DB_CONN_MAX_AGE,
            "OPTIONS": {"connect_timeout": DB_CONNECT_TIMEOUT},
        }
    }

# --- Auth -------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
AUTH_USER_MODEL = "accounts.User"

# --- i18n / tz --------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --- Static / media ---------------------------------------------------------
# Absolute, not "static/": Vercel reads STATIC_URL to decide where to mount the
# collected files on its CDN, and a relative value is ambiguous there even
# though Django itself would normalise it.
STATIC_URL = "/static/"
# Vercel runs collectstatic automatically during the build because STATIC_ROOT
# is set, then serves the result from the CDN.
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- DRF --------------------------------------------------------------------
REST_FRAMEWORK: dict[str, Any] = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.DefaultPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "EXCEPTION_HANDLER": "apps.common.exceptions.api_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": API_TITLE,
    "DESCRIPTION": API_DESCRIPTION,
    "VERSION": API_VERSION,
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1",
}

# --- JWT (SimpleJWT) --------------------------------------------------------
from datetime import timedelta  # noqa: E402

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(env("JWT_ACCESS_MINUTES", "15") or "15")),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(env("JWT_REFRESH_DAYS", "7") or "7")),
    # Refresh-token rotation: each refresh issues a new refresh token and
    # blacklists the old one so a leaked refresh token has a short useful life.
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "TOKEN_OBTAIN_SERIALIZER": "apps.accounts.serializers.TokenObtainPairSerializer",
}

# Frontend base URL used to build password-reset links in emails.
FRONTEND_BASE_URL = env("FRONTEND_BASE_URL", "http://localhost:3000")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", BRAND_DEFAULT_FROM_EMAIL)

# --- Redis ------------------------------------------------------------------
# Redis is optional. On a VM deploy it backs the cache and the Celery broker;
# on serverless (Vercel) there is no Redis and no worker process, so an unset
# REDIS_URL degrades the app to local-memory caching and inline task execution
# instead of failing every request that touches either.
REDIS_URL = env("REDIS_URL", "")

# --- Celery -----------------------------------------------------------------
CELERY_BROKER_URL = env("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", REDIS_URL)
# With no broker there is nothing to enqueue onto, so tasks must run inline in
# the calling process. This is forced rather than defaulted: CELERY_TASK_ALWAYS_
# EAGER=false with an empty broker is a misconfiguration (it makes every
# .delay() hang against a nonexistent broker and fail the request that
# triggered it), so the broker's absence wins over the flag.
if CELERY_BROKER_URL:
    CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
else:
    CELERY_TASK_ALWAYS_EAGER = True
# Eager tasks must not propagate failures into the caller: a Cloudinary cleanup
# or a notification send that errors should be logged, not turned into a 500 on
# the checkout that triggered it.
CELERY_TASK_EAGER_PROPAGATES = False
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE

from celery.schedules import crontab  # noqa: E402

# Periodic tasks. The FX refresh cadence is admin-tunable (storeconfig
# `currency.refresh_minutes`); this is the default schedule the worker starts with.
CELERY_BEAT_SCHEDULE = {
    "refresh-exchange-rates": {
        "task": "apps.currency.tasks.refresh_exchange_rates",
        "schedule": float(env("CURRENCY_REFRESH_SECONDS", "3600") or "3600"),
    },
    "release-expired-reservations": {
        "task": "apps.inventory.tasks.release_expired_reservations",
        "schedule": 300.0,
    },
    "poll-supplier-orders": {
        "task": "apps.fulfillment.tasks.poll_supplier_orders",
        "schedule": 600.0,
    },
    "sync-suppliers": {
        "task": "apps.suppliers.tasks.sync_all_suppliers",
        "schedule": 3600.0,
    },
    # ERP ↔ marketplace stock reconciliation, nightly 02:05 WAT (ERP runs its
    # own at 02:00; offset so they don't stampede each other).
    "reconcile-erp-inventory": {
        "task": "apps.erp_link.tasks.reconcile_erp_inventory",
        "schedule": crontab(hour=2, minute=5),
    },
    # Re-deliver any ERP webhooks whose retries are due (heals missed Celery retries).
    "retry-erp-webhooks": {
        "task": "apps.erp_link.tasks.retry_erp_webhooks",
        "schedule": crontab(minute="*/5"),
    },
}

# --- Cache ------------------------------------------------------------------
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            # Fail fast if Redis is unreachable so callers can fall back to the DB
            # (selectors swallow cache errors) instead of blocking on retries.
            "OPTIONS": {"socket_connect_timeout": 1, "socket_timeout": 1},
        }
    }
else:
    # No shared cache available. Local memory is per-process, which on
    # serverless means per-instance: a write on one instance cannot invalidate
    # another's copy. Cached entries therefore MUST carry a bounded TTL — see
    # CACHE_SETTINGS_TIMEOUT below — so stale data self-heals in seconds.
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": CACHE_LOCAL_LOCATION,
        }
    }

# How long the store-settings map is cached, in seconds. Explicit invalidation
# on write is reliable only with a shared cache; without one, this TTL is what
# bounds how long an admin change can take to show up on every instance.
# With Redis the default is None (cache until invalidated); without it, 30s.
_settings_ttl = env("CACHE_SETTINGS_TIMEOUT")
if _settings_ttl:
    CACHE_SETTINGS_TIMEOUT: int | None = int(_settings_ttl)
elif REDIS_URL:
    CACHE_SETTINGS_TIMEOUT = None
else:
    CACHE_SETTINGS_TIMEOUT = 30

# --- Multi-tenancy (SartorialEcommerce) --------------------------------------
# Isolated stores on a shared DB, scoped by tenant_id (see apps.tenants).
# Resolution: X-Tenant-Slug header > ?tenant= query > domain match > fallback.
TENANT_SLUG = env("TENANT_SLUG", "")

# ERP publication link (Phase 4): the Sartorial ERP pushes products/stock and
# receives orders back, authenticating per-tenant via TenantApiKey.
SARTORIAL_ERP_BASE_URL = env("SARTORIAL_ERP_BASE_URL", "")
SARTORIAL_ERP_API_KEY = env("SARTORIAL_ERP_API_KEY", "")
TENANT_ERP_BUSINESS_ID = env("TENANT_ERP_BUSINESS_ID", "")
# Timeout (seconds) for outbound calls to the ERP (webhook delivery, stock pull).
SARTORIAL_ERP_TIMEOUT = int(env("SARTORIAL_ERP_TIMEOUT", "10") or "10")

# --- Scheduled jobs ----------------------------------------------------------
# Shared secret guarding the HTTP cron entry point (apps/common/cron.py), used
# where there's no Celery Beat process. Vercel injects this into cron requests
# as an `Authorization: Bearer` header when set on the project. Empty disables
# the endpoint outright.
CRON_SECRET = env("CRON_SECRET", "")

# --- Logging ----------------------------------------------------------------
# Everything goes to stdout/stderr — the only log sink a serverless platform
# collects, and the right one for systemd/journald or `docker logs` too. Never
# log to a file: the filesystem is read-only on Vercel outside /tmp.
LOG_LEVEL = env("LOG_LEVEL", "INFO") or "INFO"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        # Unhandled exceptions in views. Without this, DEBUG=False swallows the
        # traceback and you get a bare 500 with no way to diagnose it.
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
        "django.db.backends": {
            "handlers": ["console"],
            "level": env("DB_LOG_LEVEL", "WARNING"),
            "propagate": False,
        },
        "apps": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
    },
}


# --- Cloudinary -------------------------------------------------------------
# Either CLOUDINARY_URL or the discrete cloud-name/key/secret trio.
# CLOUDINARY_URL packs all three credentials into one string, which is what the
# Cloudinary dashboard shows you and the more common way to configure a
# deployment. Parse it into the discrete values so both styles work and the rest
# of the codebase only has to read the trio. The discrete vars win if both are
# set, so a single override doesn't require rebuilding the whole URL.
def _cloudinary_from_url(url: str) -> tuple[str | None, str | None, str | None]:
    """Split ``cloudinary://<api_key>:<api_secret>@<cloud_name>`` into its parts."""
    from urllib.parse import unquote, urlparse

    parsed = urlparse(url)
    if parsed.scheme != "cloudinary":
        return None, None, None
    return (
        parsed.hostname or None,
        unquote(parsed.username) if parsed.username else None,
        unquote(parsed.password) if parsed.password else None,
    )


_cl_cloud, _cl_key, _cl_secret = _cloudinary_from_url(env("CLOUDINARY_URL", "") or "")

CLOUDINARY_CLOUD_NAME = env("CLOUDINARY_CLOUD_NAME") or _cl_cloud
CLOUDINARY_API_KEY = env("CLOUDINARY_API_KEY") or _cl_key
CLOUDINARY_API_SECRET = env("CLOUDINARY_API_SECRET") or _cl_secret

CLOUDINARY_STORAGE = {
    "CLOUD_NAME": CLOUDINARY_CLOUD_NAME,
    "API_KEY": CLOUDINARY_API_KEY,
    "API_SECRET": CLOUDINARY_API_SECRET,
}
CLOUDINARY_UPLOAD_FOLDER = env("CLOUDINARY_UPLOAD_FOLDER", DEFAULT_UPLOAD_FOLDER)

# Pluggable product-image backend. "cloudinary" hits the real account; "static"
# serves generated SVGs from the storefront's /public folder (key-less local dev
# / demos); "mock" keeps tests off the network. Defaults to cloudinary when a
# cloud name is configured, otherwise the static demo images.
# Uses the resolved cloud name (so CLOUDINARY_URL counts too), not the raw env
# var: configuring credentials should be enough to turn real uploads on.
CATALOG_IMAGE_BACKEND = env(
    "CATALOG_IMAGE_BACKEND",
    "cloudinary" if CLOUDINARY_CLOUD_NAME else "static",
)
# Origin the storefront serves generated product SVGs from. Empty = root-relative
# (same origin as the storefront), which is what the demo uses.
STATIC_IMAGE_BASE_URL = env("STATIC_IMAGE_BASE_URL", "")
# Where `generate_product_images` writes the SVGs (the storefront's public dir).
PRODUCT_IMAGE_OUTPUT_DIR = env(
    "PRODUCT_IMAGE_OUTPUT_DIR",
    str(BASE_DIR.parent / "frontend" / "public" / "products"),
)

# --- CORS -------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", ["http://localhost:3000"])
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = (
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
    "x-tenant-slug",
)

# --- App-specific defaults --------------------------------------------------
# FX rates provider (currency module, wired up in Phase 4).
RATES_PROVIDER = env("RATES_PROVIDER", "mock")
CURRENCY_API_NET_KEY = env("CURRENCY_API_NET_KEY")

# Payments. Provider-agnostic: "mock" | "paystack" | "flutterwave".
PAYMENT_PROVIDER = env("PAYMENT_PROVIDER", "mock")
PAYMENT_WEBHOOK_SECRET = env("PAYMENT_WEBHOOK_SECRET", "dev-webhook-secret")
PAYMENT_HTTP_TIMEOUT = int(env("PAYMENT_HTTP_TIMEOUT", "15") or "15")
# Public base URL of THIS API (used to show the webhook URL admins paste into
# the gateway dashboard). In prod set to your real domain; for local testing
# with Paystack/Flutterwave use your tunnel URL (e.g. an ngrok https URL).
API_PUBLIC_BASE_URL = env("API_PUBLIC_BASE_URL", "http://localhost:8000")
# Where the gateway redirects the shopper after paying. {order} is the order
# number; the gateway appends its own params (reference/tx_ref/status).
PAYMENT_RETURN_URL = env(
    "PAYMENT_RETURN_URL",
    f"{FRONTEND_BASE_URL.rstrip('/')}/checkout/processing?order={{order}}",
)
# Paystack (https://dashboard.paystack.com)
PAYSTACK_SECRET_KEY = env("PAYSTACK_SECRET_KEY", "")
PAYSTACK_PUBLIC_KEY = env("PAYSTACK_PUBLIC_KEY", "")
# Flutterwave (https://dashboard.flutterwave.com). SECRET_HASH must match the
# value set in the dashboard webhook settings (sent as the verif-hash header).
FLUTTERWAVE_SECRET_KEY = env("FLUTTERWAVE_SECRET_KEY", "")
FLUTTERWAVE_PUBLIC_KEY = env("FLUTTERWAVE_PUBLIC_KEY", "")
FLUTTERWAVE_SECRET_HASH = env("FLUTTERWAVE_SECRET_HASH", "")

# --- Notifications (Phase 9) ------------------------------------------------
# Provider-agnostic transactional dispatch. Email + Telegram, async via Celery.
# Email backend: console | zeptomail | django | memory
NOTIFICATIONS_EMAIL_BACKEND = env("NOTIFICATIONS_EMAIL_BACKEND", "console")
# Telegram backend: console | http | memory | disabled
NOTIFICATIONS_TELEGRAM_BACKEND = env("NOTIFICATIONS_TELEGRAM_BACKEND", "console")
NOTIFICATIONS_HTTP_TIMEOUT = int(env("NOTIFICATIONS_HTTP_TIMEOUT", "10") or "10")

# ZeptoMail (Zoho) HTTP email API. Secrets come from the environment only.
ZEPTOMAIL_API_URL = env("ZEPTOMAIL_API_URL", "https://api.zeptomail.com/v1.1/email")
ZEPTOMAIL_TOKEN = env("ZEPTOMAIL_TOKEN", "")

# Sender identity + branding used in emails.
EMAIL_FROM_ADDRESS = env("EMAIL_FROM_ADDRESS", env("DEFAULT_FROM_EMAIL", BRAND_DEFAULT_FROM_EMAIL))
EMAIL_FROM_NAME = env("EMAIL_FROM_NAME", BRAND_DEFAULT_FROM_NAME)
SUPPORT_EMAIL = env("SUPPORT_EMAIL", BRAND_DEFAULT_SUPPORT_EMAIL)
EMAIL_LOGO_URL = env("EMAIL_LOGO_URL", f"{FRONTEND_BASE_URL.rstrip('/')}/logo.png")

# Telegram bot. TELEGRAM_DEFAULT_CHAT_ID is the store-ops chat (new-order alerts).
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_DEFAULT_CHAT_ID = env("TELEGRAM_DEFAULT_CHAT_ID", "")

# --- Blog AI writer (OpenRouter) --------------------------------------------
# Admin-configurable via storeconfig (blog.openrouter_api_key / blog.ai_model);
# these env values are fallbacks. Secrets come from the environment only.
OPENROUTER_API_KEY = env("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = env("OPENROUTER_MODEL", "")
