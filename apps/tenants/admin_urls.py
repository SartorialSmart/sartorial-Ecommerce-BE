from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from .admin_views import (
    MyTenantsViewSet,
    TenantAdminViewSet,
    TenantApiKeyAdminViewSet,
    TenantMembershipAdminViewSet,
)
from .views import StoreSetupView

router = DefaultRouter()
router.register("tenants", TenantAdminViewSet, basename="admin-tenant")
router.register(
    "tenant-memberships", TenantMembershipAdminViewSet, basename="admin-tenant-membership"
)
router.register("tenant-keys", TenantApiKeyAdminViewSet, basename="admin-tenant-key")
router.register("my-stores", MyTenantsViewSet, basename="admin-my-stores")

urlpatterns = [
    path("stores/setup/", StoreSetupView.as_view(), name="admin-store-setup"),
    *router.urls,
]
