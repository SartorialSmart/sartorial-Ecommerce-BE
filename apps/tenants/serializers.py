from __future__ import annotations

from rest_framework import serializers

from .models import Tenant, TenantApiKey, TenantMembership


class TenantPublicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = ("id", "name", "slug", "type", "logo_url", "domain")
        read_only_fields = fields


class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = (
            "id",
            "name",
            "slug",
            "type",
            "status",
            "erp_business_id",
            "domain",
            "logo_url",
            "metadata",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class TenantMembershipSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = TenantMembership
        fields = ("id", "tenant", "user", "user_email", "role", "created_at")
        read_only_fields = ("id", "tenant", "user", "user_email", "created_at")


class TenantApiKeyCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)


class TenantApiKeySerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantApiKey
        fields = ("id", "tenant", "name", "prefix", "is_active", "last_used_at", "created_at")
        read_only_fields = fields
