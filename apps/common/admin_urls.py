from __future__ import annotations

from django.urls import path
from rest_framework.routers import DefaultRouter

from .admin_views import AuditLogViewSet
from .analytics_views import AdminAnalyticsView
from .sales_report_views import SalesReportView

router = DefaultRouter()
router.register("audit", AuditLogViewSet, basename="admin-audit")

urlpatterns = [
    path("analytics/", AdminAnalyticsView.as_view(), name="admin-analytics"),
    path("sales-report/", SalesReportView.as_view(), name="admin-sales-report"),
    *router.urls,
]
