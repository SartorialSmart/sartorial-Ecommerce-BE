from __future__ import annotations

from django.urls import path

from .views import TenantListView, TenantLookupView

urlpatterns = [
    path("stores/", TenantListView.as_view(), name="tenant-list"),
    path("stores/lookup/", TenantLookupView.as_view(), name="tenant-lookup"),
]
