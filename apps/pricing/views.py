"""Pricing tier views.

Public: list active tiers (no auth) — consumed by the frontend pricing page.
Admin: full CRUD (role: admin) — audit-logged.
"""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import IsAdminRole
from apps.common.audit import diff, record_audit
from apps.common.models import AuditLog

from .models import PricingTier
from .serializers import PricingTierAdminSerializer, PricingTierSerializer


class PublicPricingTierViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """List active pricing tiers for the storefront."""

    permission_classes = []
    queryset = PricingTier.objects.filter(is_active=True).order_by("sort_order", "name")
    serializer_class = PricingTierSerializer

    @extend_schema(tags=["pricing"], operation_id="list_pricing_tiers")
    def list(self, request: Request) -> Response:
        return super().list(request)


class AdminPricingTierViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Admin CRUD for pricing tiers."""

    permission_classes = [IsAdminRole]
    queryset = PricingTier.objects.all().order_by("sort_order", "name")
    serializer_class = PricingTierAdminSerializer

    def perform_create(self, serializer):
        tier = serializer.save()
        record_audit(
            actor=self.request.user,
            action=AuditLog.Action.CREATE,
            target_type="pricing.PricingTier",
            target_id=str(tier.id),
            changes={
                k: {"before": None, "after": getattr(tier, k)} for k in serializer.validated_data
            },
            metadata={"name": tier.name},
        )

    def perform_update(self, serializer):
        before = {
            f.name: getattr(serializer.instance, f.name) for f in serializer.instance._meta.fields
        }
        tier = serializer.save()
        after = {f.name: getattr(tier, f.name) for f in tier._meta.fields}
        record_audit(
            actor=self.request.user,
            action=AuditLog.Action.UPDATE,
            target_type="pricing.PricingTier",
            target_id=str(tier.id),
            changes=diff(before, after),
            metadata={"name": tier.name},
        )

    def perform_destroy(self, instance):
        record_audit(
            actor=self.request.user,
            action=AuditLog.Action.DELETE,
            target_type="pricing.PricingTier",
            target_id=str(instance.id),
            changes={"name": {"before": instance.name, "after": None}},
            metadata={"name": instance.name},
        )
        instance.delete()
