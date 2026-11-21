from django.apps import AppConfig


class ErpLinkConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.erp_link"
    verbose_name = "ERP integration link"

    def ready(self) -> None:
        from . import schema  # noqa: F401 - registers the OpenAPI auth extension
