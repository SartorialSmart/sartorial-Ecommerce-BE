"""HTTP entry point for scheduled work.

On a VM, recurring jobs run under Celery Beat (see ``CELERY_BEAT_SCHEDULE``).
Serverless platforms have no always-on process to host a scheduler, so the same
jobs are driven by an external scheduler — Vercel Cron — calling this endpoint.

The endpoint is intentionally *not* a Celery dispatcher: it calls the task
functions directly and synchronously, because with no broker configured there
is no worker to hand them to. Each job is isolated so one failure cannot stop
the rest, and the response reports per-job status for observability.

Security: the endpoint is unauthenticated in the Django sense (cron has no user)
and instead requires a shared secret. Vercel Cron automatically sends
``Authorization: Bearer $CRON_SECRET`` when a CRON_SECRET environment variable
is set on the project. If CRON_SECRET is unset the endpoint refuses to run at
all rather than exposing the jobs publicly.
"""

from __future__ import annotations

import hmac
import logging
from collections.abc import Callable
from typing import Any

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


def _jobs() -> dict[str, Callable[[], Any]]:
    """The recurring jobs, imported lazily to keep module import cheap.

    Keys mirror the names in ``CELERY_BEAT_SCHEDULE`` so the two schedules stay
    recognisably the same set of work.
    """
    from apps.currency.tasks import refresh_exchange_rates
    from apps.fulfillment.tasks import poll_supplier_orders
    from apps.inventory.tasks import release_expired_reservations
    from apps.suppliers.tasks import sync_all_suppliers

    return {
        "release-expired-reservations": release_expired_reservations,
        "poll-supplier-orders": poll_supplier_orders,
        "refresh-exchange-rates": refresh_exchange_rates,
        "sync-suppliers": sync_all_suppliers,
    }


class CronRunView(APIView):
    """Run scheduled jobs. Called by Vercel Cron, not by clients.

    ``GET /api/v1/cron/run/`` runs every job. ``?jobs=a,b`` runs a subset,
    which lets one schedule drive frequent cheap jobs and another drive the
    slow ones.
    """

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(exclude=True)
    def get(self, request: Request) -> Response:
        denied = self._authorize(request)
        if denied is not None:
            return denied

        available = _jobs()
        requested = [name for name in request.query_params.get("jobs", "").split(",") if name]
        unknown = [name for name in requested if name not in available]
        if unknown:
            return Response(
                {"detail": f"Unknown job(s): {', '.join(unknown)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        selected = requested or list(available)

        results: dict[str, Any] = {}
        failed = False
        for name in selected:
            try:
                results[name] = {"ok": True, "result": available[name]()}
            except Exception as exc:  # noqa: BLE001 - one bad job must not stop the others
                failed = True
                # Full traceback to the platform log; only the type/message to
                # the caller, so cron output can't leak internals.
                logger.exception("Scheduled job %s failed", name)
                results[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        # 207 tells the cron dashboard something needs attention while still
        # recording that the other jobs completed.
        code = status.HTTP_207_MULTI_STATUS if failed else status.HTTP_200_OK
        return Response({"ran": selected, "results": results}, status=code)

    @staticmethod
    def _authorize(request: Request) -> Response | None:
        """Return an error response if the caller isn't the scheduler."""
        secret = getattr(settings, "CRON_SECRET", "")
        if not secret:
            logger.error("CRON_SECRET is not set; refusing to run scheduled jobs over HTTP.")
            return Response(
                {"detail": "Scheduled jobs are not enabled."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        header = request.headers.get("Authorization", "")
        provided = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else ""
        # Constant-time compare so the secret can't be recovered by timing.
        if not provided or not hmac.compare_digest(provided, secret):
            return Response({"detail": "Invalid credentials."}, status=status.HTTP_403_FORBIDDEN)
        return None
