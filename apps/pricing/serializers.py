from rest_framework import serializers

from .models import PricingTier


class PricingTierSerializer(serializers.ModelSerializer):
    """Public serializer — exposes tier data for the frontend pricing cards."""

    class Meta:
        model = PricingTier
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "monthly_price",
            "annual_price",
            "platform_fee_percent",
            "features",
            "cta",
            "tagline",
            "is_featured",
            "sort_order",
        )
        read_only_fields = fields


class PricingTierAdminSerializer(serializers.ModelSerializer):
    """Admin serializer — all fields writable."""

    class Meta:
        model = PricingTier
        fields = "__all__"
