"""drf-spectacular extensions for the ERP API (registered in apps.py)."""

from __future__ import annotations

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class TenantApiKeyAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "apps.erp_link.authentication.TenantApiKeyAuthentication"
    name = "TenantApiKeyAuth"

    def get_security_definition(self, auto_schema):  # noqa: ANN001, ANN201
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "Service key (sk_…)",
            "description": (
                "Per-tenant machine-to-machine key issued by a platform admin "
                "(/api/v1/admin/tenant-keys/). Send as 'Authorization: Bearer sk_…' "
                "or 'X-Api-Key: sk_…'."
            ),
        }
