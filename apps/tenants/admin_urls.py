from __future__ import annotations

from rest_framework.routers import DefaultRouter

from .admin_views import (
    MyTenantsViewSet,
    TenantAdminViewSet,
    TenantApiKeyAdminViewSet,
    TenantMembershipAdminViewSet,
)

router = DefaultRouter()
router.register("tenants", TenantAdminViewSet, basename="admin-tenant")
router.register(
    "tenant-memberships", TenantMembershipAdminViewSet, basename="admin-tenant-membership"
)
router.register("tenant-keys", TenantApiKeyAdminViewSet, basename="admin-tenant-key")
router.register("my-stores", MyTenantsViewSet, basename="admin-my-stores")

urlpatterns = router.urls
