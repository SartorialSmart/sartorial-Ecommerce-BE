"""Payload schemas for the ERP → marketplace publication API."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from rest_framework import serializers


class ErpOptionSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=60)
    value = serializers.CharField(max_length=120)


class ErpVariantSerializer(serializers.Serializer):
    erp_variant_id = serializers.CharField(max_length=64)
    sku = serializers.CharField(max_length=64)
    price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0"))
    compare_at_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0"), required=False, allow_null=True
    )
    cost_price = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal("0"), required=False
    )
    moq = serializers.IntegerField(min_value=1, required=False, default=1)
    barcode = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    weight_grams = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False, default=True)
    options = ErpOptionSerializer(many=True, required=False, default=list)


class ErpProductSyncSerializer(serializers.Serializer):
    """One ERP product pushed to the marketplace (upsert semantics)."""

    erp_product_id = serializers.CharField(max_length=64)
    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    # draft | published | archived — archived unpublishes (never hard-deletes;
    # order history keeps its snapshots).
    status = serializers.ChoiceField(
        choices=["draft", "published", "archived"], required=False, default="published"
    )
    category_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    brand_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    is_featured = serializers.BooleanField(required=False, default=False)
    discount_percent = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        required=False,
        allow_null=True,
    )
    vat_rate_percent = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        required=False,
        allow_null=True,
    )
    vat_flat_amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0"),
        required=False,
        allow_null=True,
    )
    variants = ErpVariantSerializer(many=True)

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        payload = dict(data)
        aliases = {
            "discount": "discount_percent",
            "vat_percent": "vat_rate_percent",
            "tax_rate": "vat_rate_percent",
            "tax_rate_percent": "vat_rate_percent",
            "vat_amount": "vat_flat_amount",
            "tax_amount": "vat_flat_amount",
        }
        for alias, canonical in aliases.items():
            if canonical not in payload and alias in payload:
                payload[canonical] = payload[alias]
        return super().to_internal_value(payload)

    def validate_variants(self, variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not variants:
            raise serializers.ValidationError("At least one variant is required.")
        skus = [v["sku"] for v in variants]
        if len(skus) != len(set(skus)):
            raise serializers.ValidationError("Duplicate SKU in payload.")
        return variants


class ErpStockItemSerializer(serializers.Serializer):
    sku = serializers.CharField(max_length=64)
    quantity = serializers.IntegerField(min_value=0)


class ErpStockSyncSerializer(serializers.Serializer):
    items = ErpStockItemSerializer(many=True)

    def validate_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not items:
            raise serializers.ValidationError("At least one item is required.")
        if len(items) > 500:
            raise serializers.ValidationError("Maximum 500 items per call.")
        return items
