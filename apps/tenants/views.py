"""Public tenant endpoints (storefront discovery) + seller onboarding."""

from __future__ import annotations

from django.conf import settings
from django.utils.text import slugify
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers, status, views
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.models import Role
from apps.storeconfig import services as config_services

from . import services as tenant_services
from .models import Tenant, TenantStatus
from .serializers import TenantPublicSerializer, TenantSerializer, validate_store_slug


class TenantLookupView(generics.GenericAPIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = TenantPublicSerializer

    @extend_schema(summary="Resolve a store by slug or domain", tags=["tenants"])
    def get(self, request) -> Response:
        slug = request.query_params.get("slug")
        tenant = None
        if slug:
            tenant = Tenant.objects.filter(slug=slug, status=TenantStatus.ACTIVE).first()
        else:
            tenant = getattr(request, "tenant", None)
        if tenant is None:
            return Response({"detail": "Store not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(TenantPublicSerializer(tenant).data)


class TenantListView(generics.ListAPIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = TenantPublicSerializer

    @extend_schema(summary="List active storefronts", tags=["tenants"])
    def get_queryset(self):  # type: ignore[override]
        return Tenant.objects.filter(status=TenantStatus.ACTIVE).order_by("name")[:100]


class StoreSetupView(generics.GenericAPIView):
    """Create the caller's store during onboarding (or update the first one).

    Promotes a fresh ``customer`` account to ``seller`` so the dashboard's
    seller endpoints become usable, attaches an owner membership, and writes
    the store's identity/design settings — a brand-new account therefore starts
    with a clean, fully-owned store and nothing else.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TenantSerializer

    @extend_schema(request=dict, responses={201: TenantSerializer}, tags=["tenants"])
    def post(self, request) -> Response:
        name = str(request.data.get("name", "")).strip()
        if not name:
            return Response({"name": ["Required."]}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        membership = user.tenant_memberships.select_related("tenant").first()
        created = False

        if membership is not None:
            tenant = membership.tenant
            slug = tenant.slug
            if tenant.name != name:
                tenant.name = name
                tenant.save(update_fields=["name", "updated_at"])
        else:
            raw_slug = str(request.data.get("slug", "") or "").strip().lower() or slugify(name)
            try:
                slug = validate_store_slug(raw_slug or "my-store")
            except serializers.ValidationError as exc:
                return Response({"slug": exc.detail}, status=status.HTTP_400_BAD_REQUEST)
            if Tenant.objects.filter(slug=slug).exists():
                base = slug
                suffix = 2
                while Tenant.objects.filter(slug=f"{base}-{suffix}").exists():
                    suffix += 1
                slug = f"{base}-{suffix}"
            tenant = tenant_services.create_tenant(name=name, slug=slug, owner_email=user.email)
            created = True
            if user.role == Role.CUSTOMER:
                user.role = Role.SELLER
                user.save(update_fields=["role", "updated_at"])

        values: dict = {
            "store.name": name,
            "store.setup_complete": True,
            "store.domain": slug,
        }
        for key, data_key in (
            ("store.tagline", "tagline"),
            ("store.plan", "plan"),
            ("store.city", "city"),
            ("store.currency", "currency"),
            ("store.category", "category"),
            ("store.logo_url", "logo_url"),
            ("store.logo_public_id", "logo_public_id"),
        ):
            raw = str(request.data.get(data_key, "") or "").strip()
            if raw:
                values[key] = raw
        logo_url = values.get("store.logo_url", "")
        if logo_url:
            values["store.logo"] = logo_url
            if str(logo_url).startswith("https://"):
                tenant.logo_url = str(logo_url)
                tenant.save(update_fields=["logo_url", "updated_at"])
        template = str(request.data.get("template", "") or "").strip()
        if template:
            values["storefront.template"] = template
        accent = str(request.data.get("accent", "") or "").strip()
        if accent:
            values["storefront.accent"] = accent
        accent_fg = str(request.data.get("accent_fg", "") or "").strip()
        if accent_fg:
            values["storefront.accent_fg"] = accent_fg
        font_display = str(request.data.get("font_display", "") or "").strip()
        if font_display:
            values["storefront.font_display"] = font_display
        config_services.set_many(values, actor=user, tenant=tenant)

        return Response(
            TenantSerializer(tenant).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class LogoUploadSignatureView(views.APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: dict}, tags=["tenants"])
    def post(self, request: Request) -> Response:
        from apps.catalog.services import upload_signature

        folder = f"{settings.CLOUDINARY_UPLOAD_FOLDER}/logos"
        return Response(upload_signature({"folder": folder}))
