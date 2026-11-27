from __future__ import annotations

import re

from rest_framework import serializers

from .models import Tenant, TenantApiKey, TenantMembership

RESERVED_STORE_SLUGS = frozenset(
    {
        "www",
        "api",
        "apis",
        "app",
        "apps",
        "mail",
        "email",
        "webmail",
        "smtp",
        "pop",
        "imap",
        "mx",
        "dns",
        "ns",
        "ns1",
        "ns2",
        "cdn",
        "static",
        "assets",
        "media",
        "images",
        "img",
        "files",
        "uploads",
        "admin",
        "administrator",
        "root",
        "system",
        "sys",
        "billing",
        "invoice",
        "invoices",
        "payment",
        "payments",
        "checkout",
        "cart",
        "order",
        "orders",
        "refund",
        "returns",
        "support",
        "help",
        "contact",
        "about",
        "faq",
        "privacy",
        "terms",
        "legal",
        "status",
        "health",
        "login",
        "logout",
        "signin",
        "sign-in",
        "signup",
        "sign-up",
        "auth",
        "oauth",
        "account",
        "accounts",
        "profile",
        "user",
        "users",
        "team",
        "teams",
        "dashboard",
        "settings",
        "store",
        "stores",
        "shop",
        "catalog",
        "search",
        "blog",
        "news",
        "docs",
        "documentation",
        "developer",
        "developers",
        "sitemap",
        "robots",
        "favicon",
        "test",
        "testing",
        "dev",
        "development",
        "staging",
        "stage",
        "prod",
        "production",
        "demo",
        "sandbox",
        "localhost",
        "example",
        "sartorial",
        "sartorialsmart",
        "ecommerce",
        "default",
        "public",
        "internal",
        "security",
        "ssl",
        "ftp",
        "sftp",
        "ssh",
    }
)


def normalize_store_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


def validate_store_slug(value: str) -> str:
    slug = normalize_store_slug(value)
    if not slug:
        raise serializers.ValidationError("Choose a storefront address.")
    if len(slug) > 80:
        raise serializers.ValidationError("Use 80 characters or fewer.")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", slug):
        raise serializers.ValidationError("Use letters, numbers and hyphens only.")
    if re.sub(r"-\d+$", "", slug) in RESERVED_STORE_SLUGS:
        raise serializers.ValidationError(f'"{slug}" is reserved. Choose another address.')
    return slug


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

    def validate_slug(self, value: str) -> str:
        return validate_store_slug(value)


class TenantMembershipSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    user_name = serializers.CharField(source="user.full_name", read_only=True)

    class Meta:
        model = TenantMembership
        fields = ("id", "tenant", "user", "user_email", "user_name", "role", "created_at")
        read_only_fields = ("id", "tenant", "user", "user_email", "user_name", "created_at")


class TenantApiKeyCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)


class TenantApiKeySerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantApiKey
        fields = ("id", "tenant", "name", "prefix", "is_active", "last_used_at", "created_at")
        read_only_fields = fields
