"""Publication services: ERP → marketplace catalogue/stock upserts and
outbound order/payment events → ERP.

Inbound rule (confirmed): for goods owned by an ERP business the ERP is the
source of truth — the marketplace stores a *published copy* and never edits
its prices/stock outside this service. Every upsert is keyed on the ERP's
immutable ids (``erp_product_id`` / ``erp_variant_id`` / SKU), so re-pushes
are always safe.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.catalog.models import (
    Brand,
    Category,
    OptionType,
    OptionValue,
    Product,
    Variant,
    VariantOption,
)
from apps.catalog.services import compute_options_key
from apps.common.exceptions import ConflictError
from apps.inventory.models import StockItem, Warehouse
from apps.orders.models import Order
from apps.payments.models import Payment
from apps.tenants.models import Tenant, TenantType

from .models import ERPWebhookDelivery, ErpWebhookDeliveryStatus, ErpWebhookEvent

logger = logging.getLogger(__name__)

ERP_WAREHOUSE_CODE = "erp"


def _unique_category(tenant: Tenant, name: str) -> Category:
    base = slugify(name) or "category"
    slug = base
    i = 2
    while Category.objects.filter(tenant=tenant, slug=slug).exclude(name__iexact=name).exists():
        slug = f"{base}-{i}"
        i += 1
    category, _ = Category.objects.get_or_create(
        tenant=tenant, slug=slug, defaults={"name": name.strip()[:120] or "Category"}
    )
    return category


def _unique_brand(tenant: Tenant, name: str) -> Brand:
    base = slugify(name) or "brand"
    brand, _ = Brand.objects.get_or_create(
        tenant=tenant, slug=base, defaults={"name": name.strip()[:120] or "Brand"}
    )
    return brand


def _sync_variant_options(variant: Variant, option_pairs: list[dict[str, str]]) -> None:
    product = variant.product
    value_ids: list[int] = []
    for pos, pair in enumerate(option_pairs):
        name = (pair.get("name") or "").strip()
        value = (pair.get("value") or "").strip()
        if not name or not value:
            continue
        option_type, _ = OptionType.objects.get_or_create(
            product=product, name=name, defaults={"position": pos}
        )
        option_value, _ = OptionValue.objects.get_or_create(
            option_type=option_type, value=value, defaults={"position": pos}
        )
        value_ids.append(option_value.id)

    valid_ids = list(OptionValue.objects.filter(id__in=value_ids).values_list("id", flat=True))
    variant.variant_options.all().delete()
    VariantOption.objects.bulk_create(
        [VariantOption(variant=variant, option_value_id=vid) for vid in valid_ids]
    )
    variant.options_key = compute_options_key(valid_ids) if valid_ids else ""


def upsert_product(*, tenant: Tenant, payload: dict[str, Any]) -> dict[str, Any]:
    """Create or update the marketplace copy of an ERP product."""
    variants = payload["variants"]
    status = payload.get("status", "published")

    with transaction.atomic():
        product = Product.objects.filter(erp_product_id=payload["erp_product_id"]).first()
        if product is not None and product.tenant_id != tenant.id:
            raise ConflictError(
                "ERP product id is bound to a different store.", code="erp_id_conflict"
            )

        category = None
        if payload.get("category_name"):
            category = _unique_category(tenant, str(payload["category_name"]))
        brand = None
        if payload.get("brand_name"):
            brand = _unique_brand(tenant, str(payload["brand_name"]))

        created = product is None
        if created:
            product = Product(tenant=tenant, erp_product_id=payload["erp_product_id"], slug="")
        product.title = payload["title"]
        product.description = payload.get("description", "") or ""
        product.is_active = status != "archived"
        product.is_flash_sale = False if created else product.is_flash_sale
        product.category = category
        product.brand = brand
        product.is_featured = bool(payload.get("is_featured", False))
        product.save()

        seen_variant_ids: list[str] = []
        results: list[dict[str, Any]] = []
        for vdata in variants:
            variant = _upsert_variant(product=product, vdata=vdata)
            seen_variant_ids.append(str(variant.erp_variant_id))
            results.append(
                {
                    "erp_variant_id": variant.erp_variant_id,
                    "sku": variant.sku,
                    "variant_id": variant.id,
                    "created": variant._erp_created,
                }
            )

        # Variants that disappeared from the ERP payload are pulled from sale
        # (never hard-deleted — order lines snapshot them).
        stale = (
            product.variants.filter(erp_variant_id__isnull=False)
            .exclude(erp_variant_id__in=seen_variant_ids)
            .update(is_active=False)
        )

    return {
        "status": "ok",
        "created": created,
        "product_id": product.id,
        "variants": results,
        "deactivated_variants": stale,
    }


def _upsert_variant(*, product: Product, vdata: dict[str, Any]) -> Variant:
    erp_variant_id = str(vdata["erp_variant_id"])
    sku = str(vdata["sku"]).strip()

    variant = Variant.objects.filter(erp_variant_id=erp_variant_id).first()
    if variant is not None and variant.product.tenant_id != product.tenant_id:
        raise ConflictError(
            f"ERP variant id is bound to a different store (sku {sku}).",
            code="erp_id_conflict",
        )
    if variant is None:
        variant = Variant.objects.filter(sku=sku).first()
        if variant is not None and variant.product.tenant_id != product.tenant_id:
            raise ConflictError(f"SKU {sku} is already used by another store.", code="sku_conflict")
        if variant is not None and variant.erp_variant_id not in (None, "", erp_variant_id):
            raise ConflictError(
                f"SKU {sku} is already bound to a different ERP variant.",
                code="sku_conflict",
            )

    created = variant is None
    if created:
        variant = Variant(
            product=product, sku=sku, price=vdata["price"], erp_variant_id=erp_variant_id
        )
    else:
        variant.product = product
        variant.erp_variant_id = erp_variant_id
        variant.sku = sku
        variant.price = vdata["price"]
    variant.cost_price = vdata.get("cost_price") or Decimal("0")
    variant.moq = int(vdata.get("moq", 1) or 1)
    variant.barcode = str(vdata.get("barcode", "") or "")
    variant.weight_grams = vdata.get("weight_grams")
    variant.is_active = bool(vdata.get("is_active", True))
    variant.save()

    _sync_variant_options(variant, list(vdata.get("options") or []))
    variant.save(update_fields=["options_key", "updated_at"])
    variant._erp_created = created
    return variant


def erp_warehouse(tenant: Tenant) -> Warehouse:
    """The tenant's ERP-fed stocking warehouse (created on first push)."""
    warehouse = Warehouse.objects.filter(tenant=tenant, code=ERP_WAREHOUSE_CODE).first()
    if warehouse is not None:
        return warehouse
    has_default = Warehouse.objects.filter(tenant=tenant, is_default=True).exists()
    warehouse, _ = Warehouse.objects.get_or_create(
        tenant=tenant,
        code=ERP_WAREHOUSE_CODE,
        defaults={"name": "ERP stock", "is_default": not has_default},
    )
    return warehouse


@transaction.atomic
def set_stock_levels(*, tenant: Tenant, items: list[dict[str, Any]]) -> dict[str, Any]:
    warehouse = erp_warehouse(tenant)
    results: list[dict[str, Any]] = []
    for item in items:
        sku = str(item["sku"]).strip()
        quantity = int(item["quantity"])
        variant = (
            Variant.objects.select_related("product")
            .filter(product__tenant=tenant, sku=sku)
            .first()
        )
        if variant is None:
            results.append({"sku": sku, "status": "unknown_sku"})
            continue
        stock, _ = StockItem.objects.get_or_create(
            variant=variant, warehouse=warehouse, defaults={"on_hand": quantity}
        )
        stock.on_hand = quantity
        stock.full_stock = max(stock.full_stock, quantity)
        stock.save(update_fields=["on_hand", "full_stock", "updated_at"])
        results.append({"sku": sku, "status": "ok", "on_hand": quantity})
    unknown = sum(1 for r in results if r["status"] != "ok")
    return {"status": "ok" if not unknown else "partial", "results": results}


def stock_snapshot(*, tenant: Tenant) -> list[dict[str, Any]]:
    """Current available stock per ERP-linked variant (for pull/reconciliation)."""
    variants = (
        Variant.objects.select_related("product")
        .filter(product__tenant=tenant, is_active=True, product__is_active=True)
        .order_by("sku")
    )
    rows: list[dict[str, Any]] = []
    for variant in variants:
        items = StockItem.objects.filter(variant=variant)
        on_hand = sum(s.on_hand for s in items)
        reserved = sum(s.reserved for s in items)
        rows.append(
            {
                "sku": variant.sku,
                "erp_variant_id": variant.erp_variant_id,
                "on_hand": on_hand,
                "reserved": reserved,
                "available": max(on_hand - reserved, 0),
            }
        )
    return rows


# --- Outbound events (marketplace → ERP) -------------------------------------

_WEBHOOK_PATH = "/api/v1/ecommerce/webhooks/marketplace/"
_MAX_ATTEMPTS = 8


def _erp_base_url() -> str:
    return str(getattr(settings, "SARTORIAL_ERP_BASE_URL", "") or "").rstrip("/")


def _erp_api_key() -> str:
    return str(getattr(settings, "SARTORIAL_ERP_API_KEY", "") or "")


def _order_payload(order: Order) -> dict[str, Any]:
    lines = []
    for line in order.lines.select_related("variant"):
        variant = line.variant
        lines.append(
            {
                "sku": line.sku,
                "erp_variant_id": getattr(variant, "erp_variant_id", None) if variant else None,
                "title": line.title,
                "quantity": line.quantity,
                "unit_price_base": str(line.unit_price_base),
                "line_total_base": str(line.line_total_base),
                "unit_price_charged": str(line.unit_price_charged),
                "line_total_charged": str(line.line_total_charged),
            }
        )
    return {
        "order_number": order.number,
        "erp_business_id": order.tenant.erp_business_id if order.tenant else None,
        "tenant_slug": order.tenant.slug if order.tenant else None,
        "status": order.status,
        "currency": order.currency,
        "base_currency": order.base_currency,
        "subtotal_base": str(order.subtotal_base),
        "discount_base": str(order.discount_base),
        "total_base": str(order.total_base),
        "total_charged": str(order.total_charged),
        "contact_email": order.contact_email,
        "contact_name": order.contact_name,
        "shipping": {
            "name": order.ship_name,
            "line1": order.ship_line1,
            "line2": order.ship_line2,
            "city": order.ship_city,
            "region": order.ship_region,
            "postal_code": order.ship_postal_code,
            "country": order.ship_country,
            "phone": order.ship_phone,
        },
        "lines": lines,
        "placed_at": order.created_at.isoformat() if order.created_at else None,
    }


def _payment_payload(payment: Payment) -> dict[str, Any]:
    return {
        "order_number": payment.order.number,
        "erp_business_id": payment.order.tenant.erp_business_id if payment.order.tenant else None,
        "tenant_slug": payment.order.tenant.slug if payment.order.tenant else None,
        "payment_reference": payment.intent_id,
        "provider": payment.provider,
        "status": payment.status,
        "amount": str(payment.amount),
        "currency": payment.currency,
        "paid_at": timezone.now().isoformat(),
    }


def _queue(event: str, *, tenant: Tenant, payload: dict[str, Any]) -> ERPWebhookDelivery | None:
    delivery = ERPWebhookDelivery.objects.create(event=event, tenant=tenant, payload=payload)
    from apps.erp_link import tasks

    def _enqueue() -> None:
        tasks.deliver_erp_webhook.delay(str(delivery.id))

    transaction.on_commit(_enqueue)
    return delivery


def queue_order_created(*, order_id: str) -> ERPWebhookDelivery | None:
    order = (
        Order.objects.select_related("tenant")
        .prefetch_related("lines", "lines__variant")
        .filter(id=order_id)
        .first()
    )
    if order is None or order.tenant is None:
        return None
    if order.tenant.type != TenantType.ERP_SUBSCRIBER:
        # Independent stores have no ERP to receive events.
        return None
    return _queue(ErpWebhookEvent.ORDER_CREATED, tenant=order.tenant, payload=_order_payload(order))


def queue_payment_result(*, payment_id: str, succeeded: bool) -> ERPWebhookDelivery | None:
    payment = Payment.objects.select_related("order", "order__tenant").filter(id=payment_id).first()
    if payment is None or payment.order.tenant is None:
        return None
    if payment.order.tenant.type != TenantType.ERP_SUBSCRIBER:
        return None
    event = ErpWebhookEvent.PAYMENT_SUCCEEDED if succeeded else ErpWebhookEvent.PAYMENT_FAILED
    return _queue(event, tenant=payment.order.tenant, payload=_payment_payload(payment))


def sign_payload(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def build_delivery_request(delivery: ERPWebhookDelivery) -> tuple[str, bytes, dict[str, str]]:
    base = _erp_base_url()
    url = f"{base}{_WEBHOOK_PATH}"
    body = json.dumps(
        {
            "event": delivery.event,
            "event_id": str(delivery.event_id),
            "tenant_slug": delivery.tenant.slug,
            "data": delivery.payload,
        },
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    secret = _erp_api_key()
    headers = {
        "Content-Type": "application/json",
        "X-Marketplace-Signature": f"sha256={sign_payload(body, secret)}",
        "X-Marketplace-Event": delivery.event,
        "X-Marketplace-Event-Id": str(delivery.event_id),
        "X-Marketplace-Tenant": delivery.tenant.slug,
        "X-Marketplace-Timestamp": timezone.now().isoformat(),
    }
    return url, body, headers


def next_retry_at(attempts: int) -> Any:
    backoff = min(60 * (2**attempts), 3600)
    return timezone.now() + timedelta(seconds=backoff)


def mark_delivered(delivery: ERPWebhookDelivery) -> None:
    delivery.status = ErpWebhookDeliveryStatus.DELIVERED
    delivery.delivered_at = timezone.now()
    delivery.last_error = ""
    delivery.save(update_fields=["status", "delivered_at", "last_error", "attempts", "updated_at"])


def mark_attempt_failed(
    delivery: ERPWebhookDelivery, error: str, *, permanent: bool = False
) -> None:
    delivery.attempts += 1
    delivery.last_error = error[:2000]
    if permanent or delivery.attempts >= _MAX_ATTEMPTS:
        delivery.status = ErpWebhookDeliveryStatus.FAILED
        delivery.next_retry_at = None
    else:
        delivery.status = ErpWebhookDeliveryStatus.PENDING
        delivery.next_retry_at = next_retry_at(delivery.attempts)
    delivery.save(update_fields=["attempts", "last_error", "status", "next_retry_at", "updated_at"])
