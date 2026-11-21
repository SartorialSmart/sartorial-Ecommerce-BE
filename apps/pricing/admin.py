from django.contrib import admin

from .models import PricingTier


@admin.register(PricingTier)
class PricingTierAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "slug",
        "monthly_price",
        "annual_price",
        "platform_fee_percent",
        "is_active",
        "is_featured",
        "sort_order",
    )
    list_filter = ("is_active", "is_featured")
    search_fields = ("name", "slug")
    list_editable = ("monthly_price", "annual_price", "is_active", "is_featured", "sort_order")
    ordering = ("sort_order", "name")
