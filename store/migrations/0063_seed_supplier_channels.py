import datetime

from django.db import migrations

CHANNELS = (
    ("adots_wear", "Adot's wear", "ADT"),
    ("shopaura12", "AURA", "AUR"),
    ("xclusive_ladies_clothing", "Xclusive Ladies Clothing", "XCL"),
)
# Older posts are likely sold already, and a shorter backfill keeps the first
# runs cheap.
SCRAPE_SINCE = datetime.date(2026, 10, 15)


def seed(apps, schema_editor):
    SupplierChannel = apps.get_model("store", "SupplierChannel")
    for username, title, prefix in CHANNELS:
        SupplierChannel.objects.get_or_create(
            username=username,
            defaults={"title": title, "sku_prefix": prefix, "scrape_since": SCRAPE_SINCE},
        )


def unseed(apps, schema_editor):
    SupplierChannel = apps.get_model("store", "SupplierChannel")
    SupplierChannel.objects.filter(username__in=[username for username, _, _ in CHANNELS], posts__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("store", "0062_supplier_channel_intake"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
