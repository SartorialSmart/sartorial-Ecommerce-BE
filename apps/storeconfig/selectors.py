"""Read access to settings — the single ``get_setting`` entry point.

The whole settings map is cached as one dict (cheap, rarely changes) and
invalidated on write. Callers never touch the model directly.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.cache import cache

from .models import Setting
from .schema import SETTINGS, get_spec

_CACHE_KEY = "storeconfig:all"
_SENTINEL = object()


def _cache_key(tenant: Any | None) -> str:
    if tenant is None:
        return _CACHE_KEY
    tenant_id = getattr(tenant, "id", tenant)
    return f"{_CACHE_KEY}:{tenant_id}"


def _load_overrides(tenant: Any | None) -> dict[str, Any]:
    """Raw {key: value} overrides for one scope (global when tenant is None)."""
    if tenant is None:
        qs = Setting.objects.filter(tenant__isnull=True)
    else:
        qs = Setting.objects.filter(tenant_id=getattr(tenant, "id", tenant))
    return {s.key: s.value for s in qs}


def _cached_overrides(tenant: Any | None) -> dict[str, Any]:
    key = _cache_key(tenant)
    try:
        cached = cache.get(key, _SENTINEL)
    except Exception:  # noqa: BLE001 - any cache backend failure degrades gracefully
        return _load_overrides(tenant)
    if cached is _SENTINEL:
        cached = _load_overrides(tenant)
        try:
            # TTL is None with a shared cache (invalidated explicitly on write)
            # and a short bound without one, where per-process caches can't be
            # invalidated across instances. See CACHE_SETTINGS_TIMEOUT.
            cache.set(key, cached, timeout=settings.CACHE_SETTINGS_TIMEOUT)
        except Exception:  # noqa: BLE001
            pass
    return dict(cached)


def get_all_settings(tenant: Any | None = None) -> dict[str, Any]:
    """Return {key: effective_value} for every known spec (defaults + overrides).

    With a tenant, resolution is: store override → global override
    (``tenant NULL``) → spec default. Without one, global overrides only —
    the pre-multitenant behaviour, unchanged. Each scope is cached (and
    invalidated) independently so a global write never leaves stale merges.
    """
    # The cache is an optimisation, not a dependency: if it's unavailable the
    # helpers above already serve straight from the DB.
    overrides = _cached_overrides(None)
    if tenant is not None:
        overrides = {**overrides, **_cached_overrides(tenant)}
    resolved: dict[str, Any] = {}
    for key, spec in SETTINGS.items():
        resolved[key] = overrides.get(key, spec.default)
    return resolved


def get_setting(key: str, default: Any = _SENTINEL, tenant: Any | None = None) -> Any:
    """Return the effective value of ``key``.

    Resolution order: store override → global override → spec default. Passing
    ``default`` overrides the spec default (useful for keys removed from the
    registry). Raises if the key is unknown and no explicit default is given.
    """
    spec = None
    if default is _SENTINEL:
        spec = get_spec(key)  # raises ValidationError on unknown key
    values = get_all_settings(tenant)
    if key in values:
        return values[key]
    if default is not _SENTINEL:
        return default
    return spec.default if spec else None


def invalidate_cache(tenant: Any | None = None) -> None:
    try:
        cache.delete(_cache_key(tenant))
    except Exception:  # noqa: BLE001 - cache outage must not block writes
        pass
