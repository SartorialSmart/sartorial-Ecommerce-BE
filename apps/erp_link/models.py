"""Outbound webhook deliveries + reconciliation reports for the ERP link.

The marketplace pushes product/price/stock *into* its own catalogue from the
ERP (see :mod:`apps.erp_link.services`), and sends order/payment events *out*
to the ERP. Every outbound event is recorded here before delivery so the link
is auditable, retryable and idempotent end to end.
"""

from __future__ import annotations

import uuid

from django.db import models

from apps.common.models import TimeStampedModel, UUIDModel
from apps.tenants.models import Tenant


class ErpWebhookEvent(models.TextChoices):
    ORDER_CREATED = "order.created", "Order created"
    PAYMENT_SUCCEEDED = "payment.succeeded", "Payment succeeded"
    PAYMENT_FAILED = "payment.failed", "Payment failed"


class ErpWebhookDeliveryStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    DELIVERED = "delivered", "Delivered"
    FAILED = "failed", "Failed"


class ERPWebhookDelivery(UUIDModel, TimeStampedModel):
    """One outbound event to the ERP, recorded before delivery.

    ``event_id`` is the stable reference sent as ``X-Marketplace-Event-Id``;
    the ERP dedupes on it, so re-delivery after a timeout is always safe.
    """

    event = models.CharField(max_length=40, choices=ErpWebhookEvent.choices, db_index=True)
    event_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="erp_webhook_deliveries"
    )
    payload = models.JSONField()
    status = models.CharField(
        max_length=12,
        choices=ErpWebhookDeliveryStatus.choices,
        default=ErpWebhookDeliveryStatus.PENDING,
        db_index=True,
    )
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    next_retry_at = models.DateTimeField(null=True, blank=True, db_index=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["status", "next_retry_at"]),
            models.Index(fields=["tenant", "event"]),
        ]

    def __str__(self) -> str:
        return f"{self.event} {self.event_id} ({self.status})"


class ReconciliationReport(TimeStampedModel):
    """Result of one nightly ERP ↔ marketplace stock reconciliation run."""

    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="reconciliation_reports"
    )
    ok = models.BooleanField(default=False)
    checked = models.PositiveIntegerField(default=0)
    # [{sku, erp_variant_id, marketplace_available, erp_available, difference}]
    mismatches = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True, default="")

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["tenant", "ok"])]

    def __str__(self) -> str:
        state = "ok" if self.ok else f"{len(self.mismatches)} mismatch(es)"
        return f"reconciliation[{self.tenant_id}] {state} @ {self.created_at:%Y-%m-%d}"
