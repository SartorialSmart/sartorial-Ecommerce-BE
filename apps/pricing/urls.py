from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import PublicPricingTierViewSet

router = DefaultRouter()
router.register("", PublicPricingTierViewSet, basename="pricing-tier")

urlpatterns = [
    path("", include(router.urls)),
]
