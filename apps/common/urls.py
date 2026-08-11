from __future__ import annotations

from django.urls import path

from .cron import CronRunView
from .views import HealthCheckView

urlpatterns = [
    path("health/", HealthCheckView.as_view(), name="health"),
    # Driven by an external scheduler (Vercel Cron) where Celery Beat can't run.
    path("cron/run/", CronRunView.as_view(), name="cron-run"),
]
