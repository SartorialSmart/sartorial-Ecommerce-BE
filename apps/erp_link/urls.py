from __future__ import annotations

from django.urls import path

from .views import ProductSyncView, StockSyncView

urlpatterns = [
    path("catalog/sync/", ProductSyncView.as_view(), name="erp-product-sync"),
    path("inventory/", StockSyncView.as_view(), name="erp-inventory-sync"),
]
