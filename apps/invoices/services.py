from __future__ import annotations

import html
import io
from datetime import date
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

import requests
from cloudinary.utils import cloudinary_url
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from rest_framework.exceptions import ValidationError

from apps.common.audit import record_audit
from apps.common.models import AuditLog
from apps.notifications.channels.email import EmailAttachment, EmailMessage, get_email_backend
from apps.orders.models import Order
from apps.storeconfig.selectors import get_setting

from .models import Invoice, InvoiceStatus


def resolve_logo_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith("https://"):
        return raw
    if raw.startswith("http://") or "/" in raw:
        return ""
    try:
        resolved, _ = cloudinary_url(raw, secure=True)
        return resolved if resolved.startswith("https://") else ""
    except Exception:
        return ""


def _logo_image(value: str, width: float, height: float) -> Image | None:
    url = resolve_logo_url(value)
    if not url or urlparse(url).scheme != "https":
        return None
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        content = response.content
        if not content or len(content) > 5_000_000:
            return None
        image = Image(io.BytesIO(content))
        scale = min(width / image.imageWidth, height / image.imageHeight)
        image.drawWidth = image.imageWidth * scale
        image.drawHeight = image.imageHeight * scale
        return image
    except Exception:
        return None


def _money(value: Decimal, currency: str) -> str:
    return f"{currency} {value:,.2f}"


def build_invoice_pdf(invoice: Invoice) -> bytes:
    invoice.refresh_from_db()
    order = invoice.order
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Invoice {invoice.number}",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "InvoiceTitle",
        parent=styles["Heading1"],
        fontSize=26,
        spaceAfter=4,
        textColor=colors.HexColor("#5E0D24"),
    )
    body = styles["BodyText"]
    small = ParagraphStyle("InvoiceSmall", parent=body, fontSize=9, leading=12)
    right = ParagraphStyle("InvoiceRight", parent=body, alignment=TA_RIGHT)

    seller_logo = _logo_image(invoice.seller_logo_url, 120, 42)
    customer_logo = _logo_image(invoice.customer_logo_url, 100, 36)
    seller_cell = seller_logo or Paragraph(
        f"<b>{html.escape(invoice.seller_name or invoice.number)}</b>", body
    )
    customer_cell = customer_logo or Paragraph(
        f"<b>{html.escape(invoice.customer_name or 'Customer')}</b>", right
    )
    header = Table([[seller_cell, customer_cell]], colWidths=[250, 250])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))

    meta = Table(
        [
            ["Invoice", invoice.number],
            ["Order", order.number],
            ["Issued", invoice.issue_date.isoformat()],
            ["Due", invoice.due_date.isoformat() if invoice.due_date else "—"],
            ["Status", invoice.status.upper()],
        ],
        colWidths=[90, 410],
    )
    meta.setStyle(
        TableStyle(
            [
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#666666")),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )

    bill_to = Paragraph(
        "<b>Bill to</b><br/>"
        f"{html.escape(invoice.customer_name or 'Customer')}<br/>"
        f"{html.escape(invoice.customer_email or '')}<br/>"
        f"{html.escape(order.ship_line1 or '')}<br/>"
        f"{html.escape(order.ship_city or '')} {html.escape(order.ship_postal_code or '')}",
        body,
    )
    seller = Paragraph(
        "<b>From</b><br/>"
        f"{html.escape(invoice.seller_name or '')}<br/>"
        f"{html.escape(invoice.seller_email or '')}",
        body,
    )
    parties = Table([[bill_to, seller]], colWidths=[250, 250])
    parties.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))

    rows: list[list[str]] = [["Item", "SKU", "Qty", "Unit", "Amount"]]
    for line in order.lines.all():
        rows.append(
            [
                html.escape(line.title),
                html.escape(line.sku),
                str(line.quantity),
                _money(line.unit_price_charged, invoice.currency),
                _money(line.line_total_charged, invoice.currency),
            ]
        )
    items = Table(rows, colWidths=[190, 90, 35, 90, 95], repeatRows=1)
    items.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3E9E9")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#DDDDDD")),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
            ]
        )
    )

    totals = Table(
        [
            ["Subtotal", _money(invoice.subtotal, invoice.currency)],
            ["Discount", _money(invoice.discount, invoice.currency)],
            ["VAT", _money(invoice.vat, invoice.currency)],
            ["Total due", _money(invoice.total, invoice.currency)],
        ],
        colWidths=[420, 80],
    )
    totals.setStyle(
        TableStyle(
            [
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEABOVE", (0, -1), (-1, -1), 0.75, colors.HexColor("#5E0D24")),
            ]
        )
    )

    story: list[Any] = [
        header,
        Spacer(1, 14),
        Paragraph("INVOICE", title_style),
        meta,
        Spacer(1, 14),
        parties,
        Spacer(1, 18),
        items,
        Spacer(1, 10),
        totals,
    ]
    if invoice.notes:
        story.extend(
            [
                Spacer(1, 16),
                Paragraph("<b>Notes</b>", body),
                Paragraph(html.escape(invoice.notes).replace("\n", "<br/>"), small),
            ]
        )
    story.append(Spacer(1, 20))
    story.append(
        Paragraph(
            "Thank you for shopping with us. Please quote this invoice number with any enquiry.",
            small,
        )
    )
    doc.build(story)
    return buffer.getvalue()


def create_invoice(
    *,
    order: Order,
    actor: Any,
    customer_name: str = "",
    customer_email: str = "",
    customer_logo_url: str = "",
    notes: str = "",
    due_date: date | None = None,
) -> Invoice:
    if Invoice.objects.filter(order=order).exists():
        raise ValidationError("An invoice already exists for this order.")
    tenant = order.tenant
    seller_name = get_setting("store.name", tenant=tenant) or (tenant.name if tenant else "")
    seller_email = get_setting("store.support_email", tenant=tenant) or ""
    seller_logo_url = (
        get_setting("store.logo_url", tenant=tenant)
        or get_setting("store.logo_public_id", tenant=tenant)
        or (tenant.logo_url if tenant else "")
    )
    invoice = Invoice.objects.create(
        tenant=tenant,
        order=order,
        customer_name=customer_name.strip() or order.ship_name or order.contact_name,
        customer_email=customer_email.strip() or order.contact_email or order.payer_email,
        customer_logo_url=customer_logo_url.strip(),
        seller_name=seller_name,
        seller_email=seller_email,
        seller_logo_url=seller_logo_url,
        currency=order.currency,
        subtotal=order.subtotal_charged,
        discount=order.discount_charged,
        vat=order.vat_charged,
        total=order.total_charged,
        due_date=due_date,
        notes=notes.strip(),
    )
    record_audit(
        actor=actor,
        action=AuditLog.Action.CREATE,
        target_type="invoices.Invoice",
        target_id=str(invoice.id),
        changes={"number": {"before": "", "after": invoice.number}},
        metadata={"order": order.number},
    )
    return invoice


def send_invoice(
    *, invoice: Invoice, to: str, subject: str = "", message: str = ""
) -> dict[str, Any]:
    pdf = build_invoice_pdf(invoice)
    filename = f"{invoice.number}.pdf"
    text = message.strip() or (
        f"Please find invoice {invoice.number} for order {invoice.order.number} attached."
    )
    html_body = (
        "<p>"
        + html.escape(text).replace("\n", "<br/>")
        + f"</p><p>Invoice <strong>{html.escape(invoice.number)}</strong> · "
        + f"Total {html.escape(_money(invoice.total, invoice.currency))}</p>"
    )
    email = EmailMessage(
        to=to,
        subject=subject.strip() or f"Invoice {invoice.number}",
        html=html_body,
        text=text,
        attachments=[EmailAttachment(filename, pdf, "application/pdf")],
    )
    try:
        response = get_email_backend().send(email)
    except Exception as exc:
        invoice.send_error = str(exc)[:500]
        invoice.save(update_fields=["send_error", "updated_at"])
        raise
    invoice.status = InvoiceStatus.SENT
    invoice.last_sent_at = timezone.now()
    invoice.send_error = ""
    invoice.save(update_fields=["status", "last_sent_at", "send_error", "updated_at"])
    return response
