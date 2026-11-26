from __future__ import annotations

from django.urls import path

from .views import LogoUploadSignatureView, TenantListView, TenantLookupView

urlpatterns = [
    path("stores/", TenantListView.as_view(), name="tenant-list"),
    path("stores/lookup/", TenantLookupView.as_view(), name="tenant-lookup"),
    path(
        "logos/upload-signature/", LogoUploadSignatureView.as_view(), name="logo-upload-signature"
    ),
]
