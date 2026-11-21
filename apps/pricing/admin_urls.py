from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AdminPricingTierViewSet

router = DefaultRouter()
router.register("", AdminPricingTierViewSet, basename="admin-pricing-tier")

urlpatterns = [
    path("", include(router.urls)),
]
