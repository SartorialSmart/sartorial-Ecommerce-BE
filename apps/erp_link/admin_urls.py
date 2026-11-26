from __future__ import annotations

from django.urls import path

from .admin_views import SellerErpKeyView, SellerErpLinkView

urlpatterns = [
    path("erp-link/", SellerErpLinkView.as_view(), name="admin-erp-link"),
    path("erp-link/key/", SellerErpKeyView.as_view(), name="admin-erp-link-key"),
]
