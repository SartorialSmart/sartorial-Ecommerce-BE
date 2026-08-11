"""Production settings.

All sensitive values must come from the environment; this module only tightens
security defaults and fails loudly if the secret key was left at its dev value.

This module serves both deploy targets: a long-lived VM (gunicorn + Celery
workers + Redis, see ``deploy/``) and Vercel's serverless Python runtime. The
differences are detected from the environment rather than split into a separate
settings module, so there is exactly one production code path to reason about.
"""

from __future__ import annotations

from urllib.parse import urlparse

from .base import *  # noqa: F401,F403
from .base import ALLOWED_HOSTS, CORS_ALLOWED_ORIGINS, SECRET_KEY, env, env_bool, env_list

DEBUG = False

# Fail loudly, here, on a missing or placeholder signing key. Django's own
# "SECRET_KEY must not be empty" surfaces much later — from inside whichever
# third-party app happens to read settings.SECRET_KEY at import time — as a
# traceback that points at that library rather than at the real cause. An empty
# value is the common case: `DJANGO_SECRET_KEY="$UNSET_VAR"` exports an empty
# string, which is present in the environment and so overrides the default.
_placeholder_keys = {
    "insecure-dev-key-change-me",
    "change-me-in-production",
    "change-me",
}
if not SECRET_KEY or not SECRET_KEY.strip():
    raise RuntimeError(
        "DJANGO_SECRET_KEY is empty. Note that exporting an unset shell variable "
        '(DJANGO_SECRET_KEY="$SOME_UNSET_VAR") yields an empty string rather than '
        "leaving it unset. Generate one with:\n"
        '  python -c "import secrets; print(secrets.token_urlsafe(64))"'
    )
if SECRET_KEY in _placeholder_keys:
    raise RuntimeError(
        f"DJANGO_SECRET_KEY is still the placeholder {SECRET_KEY!r}. Generate a real one with:\n"
        '  python -c "import secrets; print(secrets.token_urlsafe(64))"'
    )
# Signing keys shorter than this can't carry 256 bits of entropy, and JWTs are
# signed with HS256 off this value.
if len(SECRET_KEY) < 50:
    raise RuntimeError(
        f"DJANGO_SECRET_KEY is too short ({len(SECRET_KEY)} chars); use at least 50."
    )

# --- Platform detection ------------------------------------------------------
# Vercel injects VERCEL=1 into both the build and the runtime environment.
ON_VERCEL = env_bool("VERCEL", False) or bool(env("VERCEL_URL"))

# --- Hosts / CSRF ------------------------------------------------------------
# Vercel assigns every deployment a generated hostname (and every preview a new
# one), so a hardcoded DJANGO_ALLOWED_HOSTS list would 400 on each deploy.
# VERCEL_URL is this deployment's host; VERCEL_PROJECT_PRODUCTION_URL is the
# stable production host. Both are injected by the platform.
_vercel_hosts = [host for host in (env("VERCEL_URL"), env("VERCEL_PROJECT_PRODUCTION_URL")) if host]

# A custom domain (api.example.com) is NOT discoverable from the platform
# environment — Vercel only exposes its own *.vercel.app hostnames. Without
# this, serving the API on a custom domain returns 400 to every request while
# static assets keep working, which reads like a routing problem rather than a
# host-allowlist one. API_PUBLIC_BASE_URL already has to be set for payment
# webhooks, so treat it as authoritative for the API's own hostname too.
_public_host = urlparse(env("API_PUBLIC_BASE_URL", "") or "").hostname
if _public_host and _public_host not in {"localhost", "127.0.0.1"}:
    _vercel_hosts.append(_public_host)

if _vercel_hosts:
    ALLOWED_HOSTS = list(dict.fromkeys([*ALLOWED_HOSTS, *_vercel_hosts]))

# Preview deployments get unpredictable *.vercel.app hostnames. Opt in with
# DJANGO_ALLOW_VERCEL_PREVIEWS=1 rather than allowing the wildcard by default.
if ON_VERCEL and env_bool("DJANGO_ALLOW_VERCEL_PREVIEWS", False):
    ALLOWED_HOSTS = [*ALLOWED_HOSTS, ".vercel.app"]

# Django 4+ requires the scheme on CSRF trusted origins. The Django admin and
# the DRF browsable API both post cross-origin from the deployment host.
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", [])
CSRF_TRUSTED_ORIGINS += [f"https://{host}" for host in _vercel_hosts]
if ON_VERCEL and env_bool("DJANGO_ALLOW_VERCEL_PREVIEWS", False):
    CSRF_TRUSTED_ORIGINS.append("https://*.vercel.app")
# The storefront posts to this API with credentials, so its origin must be
# trusted for CSRF on session-authenticated (admin/browsable API) requests.
CSRF_TRUSTED_ORIGINS += [origin for origin in CORS_ALLOWED_ORIGINS if origin.startswith("https://")]
CSRF_TRUSTED_ORIGINS = list(dict.fromkeys(CSRF_TRUSTED_ORIGINS))

# --- Security hardening ------------------------------------------------------
# Vercel terminates TLS at the edge and forwards X-Forwarded-Proto, so Django
# can tell an HTTPS request from a plain one.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Redirecting at the app layer on Vercel is redundant (the edge already serves
# HTTPS only) and risks a loop if the proxy header is ever missing, so default
# it off there and on everywhere else.
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", not ON_VERCEL)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = int(env("DJANGO_SECURE_HSTS_SECONDS", "31536000") or "31536000")
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# --- Background work ---------------------------------------------------------
# On a VM, Celery workers consume from Redis. On Vercel there is no worker and
# no broker, so tasks must run inline in the request that triggers them —
# base.py already defaults CELERY_TASK_ALWAYS_EAGER to "no broker configured".
# Recurring work that Celery Beat would have run is driven by Vercel Cron
# instead; see apps/common/cron.py.
