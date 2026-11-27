"""Subscription pricing tiers.

Each tier defines a monthly / annual price in the smallest currency unit (kobo
for NGN), the platform fee percent, and a feature list. The frontend consumes
the public list endpoint to render pricing cards and checkout plan selection.
"""

from __future__ import annotations

from django.db import models

from apps.common.models import BaseModel


class PricingTier(BaseModel):
    """A subscription tier (e.g. Ankara free, Aso-Òkè, Maison)."""

    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=60, unique=True)
    description = models.TextField(blank=True)

    monthly_price = models.PositiveIntegerField(
        default=0,
        help_text="Monthly price in the smallest currency unit (e.g. NGN kobo).",
    )
    annual_price = models.PositiveIntegerField(
        default=0,
        help_text="Annual price in the smallest currency unit (e.g. NGN kobo).",
    )

    platform_fee_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Platform fee taken on each sale (e.g. 2.00 for 2%).",
    )

    features = models.JSONField(
        default=list,
        blank=True,
        help_text="List of feature strings rendered on the pricing card.",
    )
    cta = models.CharField(max_length=40, blank=True, help_text="Call-to-action button text.")
    tagline = models.CharField(max_length=160, blank=True)

    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "name")
        verbose_name = "pricing tier"
        verbose_name_plural = "pricing tiers"

    def __str__(self) -> str:
        return self.name
