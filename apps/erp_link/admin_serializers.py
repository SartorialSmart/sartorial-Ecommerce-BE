from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.tenants.models import Tenant


class LinkErpSerializer(serializers.Serializer[dict[str, Any]]):
    erp_business_id = serializers.CharField(required=False, max_length=80, allow_blank=True)
    erp_seller_id = serializers.CharField(required=False, max_length=80, allow_blank=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        value = str(attrs.get("erp_business_id") or attrs.get("erp_seller_id") or "").strip()
        if not value:
            raise serializers.ValidationError(
                {"erp_business_id": "Enter the business ID or seller ID from your ERP account."}
            )
        if len(value) > 80:
            raise serializers.ValidationError({"erp_business_id": "Use 80 characters or fewer."})
        clash = Tenant.objects.filter(erp_business_id=value)
        if self.context.get("tenant") is not None:
            clash = clash.exclude(id=self.context["tenant"].id)
        if clash.exists():
            raise serializers.ValidationError(
                {"erp_business_id": "That ERP account is already linked to another store."}
            )
        attrs["erp_business_id"] = value
        return attrs
