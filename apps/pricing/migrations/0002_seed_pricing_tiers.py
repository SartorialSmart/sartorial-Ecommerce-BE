from django.db import migrations

ANKARA_FEATURES = [
    "Free sartorial.store subdomain",
    "Up to 20 products",
    "Storefront designer basics",
    "Sell on the Sartorial marketplace",
    "Paystack, M-Pesa & card checkout",
    "2% platform fee",
]

ASO_OKE_FEATURES = [
    "Everything in Ankara",
    "Custom domain & branded email",
    "Full store designer + all themes",
    "Abandoned-cart recovery",
    "Sales & visitor analytics",
    "Pan-African shipping labels",
    "0.5% platform fee",
]

MAISON_FEATURES = [
    "Everything in Aso-Òkè",
    "Up to 5 storefronts",
    "Wholesale & B2B ordering portal",
    "Runway drop scheduling",
    "Fashion-week directory listing",
    "Concierge onboarding",
    "0% platform fee",
]


def seed_tiers(apps, schema_editor):
    PricingTier = apps.get_model("pricing", "PricingTier")
    PricingTier.objects.bulk_create(
        [
            PricingTier(
                name="Ankara",
                slug="ankara",
                description="Start threading your first sale.",
                monthly_price=0,
                annual_price=0,
                platform_fee_percent=2.00,
                features=ANKARA_FEATURES,
                cta="Start free",
                tagline="Start threading your first sale.",
                is_active=True,
                is_featured=False,
                sort_order=1,
            ),
            PricingTier(
                name="Aso-Òkè",
                slug="asooke",
                description="For labels ready to grow loud.",
                monthly_price=38413,
                annual_price=30466,
                platform_fee_percent=0.50,
                features=ASO_OKE_FEATURES,
                cta="Choose Aso-Òkè",
                tagline="For labels ready to grow loud.",
                is_active=True,
                is_featured=True,
                sort_order=2,
            ),
            PricingTier(
                name="Maison",
                slug="maison",
                description="For fashion houses with runway plans.",
                monthly_price=104644,
                annual_price=83450,
                platform_fee_percent=0.00,
                features=MAISON_FEATURES,
                cta="Go Maison",
                tagline="For fashion houses with runway plans.",
                is_active=True,
                is_featured=False,
                sort_order=3,
            ),
        ]
    )


def unseed_tiers(apps, schema_editor):
    PricingTier = apps.get_model("pricing", "PricingTier")
    PricingTier.objects.filter(slug__in=["ankara", "asooke", "maison"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("pricing", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_tiers, unseed_tiers),
    ]
