from __future__ import annotations

import secrets

from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel
from apps.orders.models import Order
from apps.tenants.models import TenantScopedModel


def generate_invoice_number() -> str:
    return f"INV-{secrets.token_hex(4).upper()}"


class InvoiceStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SENT = "sent", "Sent"
    PAID = "paid", "Paid"


class Invoice(TenantScopedModel, BaseModel):
    number = models.CharField(
        max_length=20, unique=True, default=generate_invoice_number, editable=False
    )
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="invoice")
    status = models.CharField(
        max_length=12, choices=InvoiceStatus.choices, default=InvoiceStatus.DRAFT, db_index=True
    )
    customer_name = models.CharField(max_length=255, blank=True)
    customer_email = models.EmailField(blank=True)
    customer_logo_url = models.URLField(blank=True)
    seller_name = models.CharField(max_length=255, blank=True)
    seller_email = models.EmailField(blank=True)
    seller_logo_url = models.URLField(blank=True)
    currency = models.CharField(max_length=3, default="USD")
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vat = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    issue_date = models.DateField(default=timezone.localdate)
    due_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    send_error = models.TextField(blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.number
