"""Public blog API (read-only)."""

from __future__ import annotations

from rest_framework import viewsets
from rest_framework.permissions import AllowAny

from .models import BlogCategory
from .selectors import published_posts, search_posts
from .serializers import (
    BlogCategorySerializer,
    BlogPostDetailSerializer,
    BlogPostListSerializer,
)


class BlogPostViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [AllowAny]
    serializer_class = BlogPostListSerializer
    lookup_field = "slug"

    def get_queryset(self):  # type: ignore[override]
        from apps.tenants.services import get_effective_tenant, tenant_filter

        qs = published_posts()
        if getattr(self, "swagger_fake_view", False):
            return qs
        qs = qs.filter(**tenant_filter(get_effective_tenant(self.request)))
        params = self.request.query_params
        if cat := params.get("category"):
            qs = qs.filter(category__slug=cat)
        if tag := params.get("tag"):
            qs = qs.filter(tags__contains=[tag])
        if term := params.get("search"):
            qs = search_posts(qs, term)
        return qs

    def get_serializer_class(self):  # type: ignore[override]
        if self.action == "retrieve":
            return BlogPostDetailSerializer
        return BlogPostListSerializer


class BlogCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [AllowAny]
    serializer_class = BlogCategorySerializer
    lookup_field = "slug"

    def get_queryset(self):  # type: ignore[override]
        from apps.tenants.services import get_effective_tenant, tenant_filter

        qs = BlogCategory.objects.all()
        if getattr(self, "swagger_fake_view", False):
            return qs
        return qs.filter(**tenant_filter(get_effective_tenant(self.request)))
