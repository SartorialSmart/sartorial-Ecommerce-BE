"""Celery tasks for the ERP link: webhook delivery + reconciliation."""

from __future__ import annotations

import logging
from typing import Any

import requests
from celery import shared_task
from django.conf import settings

from . import services
from .models import ERPWebhookDelivery, ErpWebhookDeliveryStatus

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0, default_retry_delay=60)
def deliver_erp_webhook(self: Any, delivery_id: str) -> dict[str, Any]:
    """Deliver one queued ERP webhook; idempotent end to end."""
    delivery = ERPWebhookDelivery.objects.select_related("tenant").filter(id=delivery_id).first()
    if delivery is None:
        return {"status": "missing"}
    if delivery.status == ErpWebhookDeliveryStatus.DELIVERED:
        return {"status": "already_delivered"}

    base = services._erp_base_url()
    secret = services._erp_api_key()
    if not base or not secret:
        services.mark_attempt_failed(delivery, "SARTORIAL_ERP_BASE_URL/API_KEY not configured")
        # Not an attempt we count against the ERP — leave pending for retry
        # once the platform is configured.
        return {"status": "not_configured"}

    url, body, headers = services.build_delivery_request(delivery)
    timeout = int(getattr(settings, "SARTORIAL_ERP_TIMEOUT", 10) or 10)
    try:
        response = requests.post(url, data=body, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        logger.warning("ERP webhook %s delivery failed: %s", delivery.event_id, exc)
        services.mark_attempt_failed(delivery, f"{type(exc).__name__}: {exc}")
        return {"status": "retry_scheduled"}

    if response.status_code < 300:
        services.mark_delivered(delivery)
        return {"status": "delivered", "http": response.status_code}

    # 4xx means the ERP rejected the payload/signature — retrying won't help.
    permanent = 400 <= response.status_code < 500
    detail = response.text[:500] if response.text else ""
    logger.warning(
        "ERP webhook %s rejected: HTTP %s %s", delivery.event_id, response.status_code, detail
    )
    services.mark_attempt_failed(
        delivery, f"HTTP {response.status_code}: {detail}", permanent=permanent
    )
    return {"status": "failed" if permanent else "retry_scheduled", "http": response.status_code}


@shared_task
def retry_erp_webhooks() -> dict[str, int]:
    """Re-deliver due pending webhooks (called on cron; heals missed retries)."""
    from django.utils import timezone

    due = (
        ERPWebhookDelivery.objects.filter(
            status=ErpWebhookDeliveryStatus.PENDING,
        )
        .filter(next_retry_at__isnull=True)
        .select_related("tenant")
    )
    due_retry = ERPWebhookDelivery.objects.filter(
        status=ErpWebhookDeliveryStatus.PENDING, next_retry_at__lte=timezone.now()
    ).select_related("tenant")
    ids = list(due.values_list("id", flat=True)[:50]) + list(
        due_retry.values_list("id", flat=True)[:50]
    )
    for delivery_id in ids:
        deliver_erp_webhook(str(delivery_id))
    return {"attempted": len(ids)}


@shared_task
def reconcile_erp_inventory() -> dict[str, Any]:
    """Compare ERP vs marketplace available stock for every ERP-linked store.

    Writes one ``ReconciliationReport`` per tenant; a mismatch also logs an
    ERROR so the alerting pipeline (and ops chat) sees it. Never raises —
    one broken store must not stop the others.
    """
    from apps.tenants.models import Tenant, TenantStatus, TenantType

    from .models import ReconciliationReport

    base = services._erp_base_url()
    secret = services._erp_api_key()
    summary: dict[str, Any] = {"tenants": 0, "mismatches": 0, "errors": 0}
    if not base or not secret:
        logger.error("reconcile_erp_inventory: SARTORIAL_ERP_BASE_URL/API_KEY not configured")
        return {**summary, "status": "not_configured"}

    tenants = Tenant.objects.filter(
        type=TenantType.ERP_SUBSCRIBER,
        status=TenantStatus.ACTIVE,
        erp_business_id__isnull=False,
    ).exclude(erp_business_id="")
    for tenant in tenants:
        summary["tenants"] += 1
        try:
            erp_rows = _fetch_erp_stock(base=base, secret=secret, tenant=tenant)
            report = _compare(tenant=tenant, erp_rows=erp_rows)
            summary["mismatches"] += len(report.mismatches)
        except Exception as exc:  # noqa: BLE001 - isolate failures per tenant
            logger.exception("reconcile_erp_inventory failed for tenant %s", tenant.slug)
            ReconciliationReport.objects.create(
                tenant=tenant, ok=False, error=f"{type(exc).__name__}: {exc}"
            )
            _alert_ops(
                f"ERP reconciliation failed for {tenant.slug}: {type(exc).__name__}: {exc}",
                tenant_slug=tenant.slug,
            )
            summary["errors"] += 1
    return summary


def _fetch_erp_stock(*, base: str, secret: str, tenant: Any) -> list[dict[str, Any]]:
    url = f"{base}/api/v1/ecommerce/marketplace/stock/"
    response = requests.get(
        url,
        params={"business_id": tenant.erp_business_id},
        headers={"Authorization": f"Bearer {secret}"},
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()
    return list(data.get("inventory", []))


def _compare(*, tenant: Any, erp_rows: list[dict[str, Any]]) -> Any:
    from .models import ReconciliationReport

    marketplace = {row["sku"]: row for row in services.stock_snapshot(tenant=tenant)}
    mismatches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in erp_rows:
        sku = str(row.get("sku") or "")
        if not sku:
            continue
        seen.add(sku)
        local = marketplace.get(sku)
        if local is None:
            mismatches.append(
                {
                    "sku": sku,
                    "erp_variant_id": row.get("erp_variant_id"),
                    "marketplace_available": None,
                    "erp_available": row.get("available"),
                    "difference": None,
                }
            )
            continue
        local_avail = int(local["available"])
        erp_avail = int(row.get("available") or 0)
        if local_avail != erp_avail:
            mismatches.append(
                {
                    "sku": sku,
                    "erp_variant_id": row.get("erp_variant_id") or local.get("erp_variant_id"),
                    "marketplace_available": local_avail,
                    "erp_available": erp_avail,
                    "difference": local_avail - erp_avail,
                }
            )
    report = ReconciliationReport.objects.create(
        tenant=tenant,
        ok=not mismatches,
        checked=len(erp_rows),
        mismatches=mismatches,
    )
    if mismatches:
        logger.error(
            "ERP reconciliation mismatch for tenant %s: %s",
            tenant.slug,
            mismatches,
        )
        _alert_ops(
            f"ERP reconciliation mismatch for {tenant.slug}: "
            f"{len(mismatches)} SKU(s) differ — see ReconciliationReport #{report.id}",
            tenant_slug=tenant.slug,
        )
    return report


def _alert_ops(message: str, *, tenant_slug: str = "") -> None:
    """Best-effort ops alert via Telegram; never raises. One alert per tenant per day."""
    from django.utils import timezone

    from apps.notifications import events
    from apps.notifications.notify import _ops_chat
    from apps.notifications.services import dispatch

    try:
        ops = _ops_chat()
        if not ops:
            logger.error("ops alert (no Telegram channel configured): %s", message)
            return
        dispatch(
            events.OPS_ERP_RECONCILIATION,
            context={"message": message},
            dedupe_key=f"erp_recon:{tenant_slug}:{timezone.now():%Y%m%d}",
            telegram_chat_id=ops,
        )
    except Exception:
        logger.exception("ops alert failed: %s", message)
