from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from apps.catalog.models import Product
from apps.storeconfig.selectors import get_all_settings

PERCENTAGE = "percentage"
FLAT = "flat"


@dataclass(frozen=True)
class VatRule:
    mode: str
    value: Decimal
    source: str


def _decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value or "0"))


def store_vat_rule(tenant: Any) -> VatRule | None:
    values = get_all_settings(tenant)
    if not values.get("tax.vat_enabled"):
        return None
    mode = str(values.get("tax.vat_type") or PERCENTAGE)
    value = (
        _decimal(values.get("tax.vat_percent"))
        if mode == PERCENTAGE
        else _decimal(values.get("tax.vat_flat_amount"))
    )
    if value <= 0:
        return None
    return VatRule(mode=mode, value=value, source="store")


def product_vat_rule(product: Product, store_rule: VatRule | None) -> VatRule | None:
    if product.erp_product_id:
        if product.vat_rate_percent is not None:
            return VatRule(mode=PERCENTAGE, value=_decimal(product.vat_rate_percent), source="erp")
        if product.vat_flat_amount is not None:
            return VatRule(mode=FLAT, value=_decimal(product.vat_flat_amount), source="erp")
    return store_rule


def vat_amount(rule: VatRule | None, line_total: Decimal, quantity: int) -> Decimal:
    if rule is None or rule.value <= 0:
        return Decimal("0")
    amount = (
        line_total * rule.value / Decimal("100")
        if rule.mode == PERCENTAGE
        else rule.value * Decimal(quantity)
    )
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
