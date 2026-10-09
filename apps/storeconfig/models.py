"""Persistence for admin-overridden settings.

Only keys an admin has explicitly changed get a row here; everything else falls
back to the spec default in :mod:`apps.storeconfig.schema`. The value is stored
as JSON keyed by the spec name, so no migration is ever needed to add a knob.
"""

from __future__ import annotations

from typing import Any

from django.db import models

from apps.common.models import TimeStampedModel


class Setting(TimeStampedModel):
    # Null tenant = platform-global override (applies to every store unless the
    # store sets its own). Per-store overrides carry the store's tenant.
    tenant = models.ForeignKey(
        "tenants.Tenant",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="settings",
        db_index=True,
    )
    key = models.CharField(max_length=120, db_index=True)
    section = models.CharField(max_length=60, db_index=True)
    # JSON wrapper so any type (bool/int/str/list/dict) round-trips losslessly.
    value = models.JSONField()

    class Meta:
        ordering = ("section", "key")
        constraints = [
            models.UniqueConstraint(fields=["tenant", "key"], name="uniq_setting_per_tenant"),
        ]

    def __str__(self) -> str:
        return self.key

    @property
    def raw_value(self) -> Any:
        return self.value
