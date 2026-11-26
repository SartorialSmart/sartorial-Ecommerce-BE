from __future__ import annotations

from rest_framework.routers import DefaultRouter

from .views import InvoiceAdminViewSet

router = DefaultRouter()
router.register("invoices", InvoiceAdminViewSet, basename="admin-invoice")

urlpatterns = router.urls
