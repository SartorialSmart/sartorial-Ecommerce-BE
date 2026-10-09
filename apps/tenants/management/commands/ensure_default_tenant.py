from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.tenants.services import get_or_create_default_tenant


class Command(BaseCommand):
    help = "Ensure the 'default' tenant exists (bootstrap for pre-multitenant data)."

    def handle(self, *args: object, **options: object) -> None:
        tenant = get_or_create_default_tenant()
        self.stdout.write(self.style.SUCCESS(f"Default tenant ready: {tenant.slug} ({tenant.id})"))
