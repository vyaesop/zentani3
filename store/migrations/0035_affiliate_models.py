from decimal import Decimal

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("store", "0034_brand_store_brand_is_acti_1b2d6f_idx_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AffiliateProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.SlugField(db_index=True, max_length=40, unique=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="affiliate_profile", to=settings.AUTH_USER_MODEL),
                ),
            ],
        ),
        migrations.CreateModel(
            name="AffiliateClick",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("session_key", models.CharField(blank=True, max_length=64, null=True)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("user_agent", models.CharField(blank=True, max_length=300)),
                ("landing_path", models.CharField(blank=True, max_length=300)),
                ("converted", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "affiliate",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="clicks", to="store.affiliateprofile"),
                ),
            ],
        ),
        migrations.CreateModel(
            name="AffiliateCommission",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("rate", models.DecimalField(decimal_places=2, default=Decimal("5.00"), max_digits=5)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=10)),
                (
                    "status",
                    models.CharField(
                        choices=[("Pending", "Pending"), ("Paid", "Paid"), ("Cancelled", "Cancelled")],
                        default="Pending",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "affiliate",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="commissions", to="store.affiliateprofile"),
                ),
                (
                    "customer",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="affiliate_purchases", to=settings.AUTH_USER_MODEL),
                ),
                (
                    "order",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="affiliate_commissions", to="store.order"),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="affiliateprofile",
            index=models.Index(fields=["is_active", "created_at"], name="store_affil_is_acti_3bb16d_idx"),
        ),
        migrations.AddIndex(
            model_name="affiliateclick",
            index=models.Index(fields=["affiliate", "created_at"], name="store_affil_affilia_694f34_idx"),
        ),
        migrations.AddIndex(
            model_name="affiliateclick",
            index=models.Index(fields=["session_key", "created_at"], name="store_affil_session_f5e643_idx"),
        ),
        migrations.AddIndex(
            model_name="affiliateclick",
            index=models.Index(fields=["converted", "created_at"], name="store_affil_convert_73ab73_idx"),
        ),
        migrations.AddIndex(
            model_name="affiliatecommission",
            index=models.Index(fields=["affiliate", "status", "created_at"], name="store_affil_affilia_8c08c4_idx"),
        ),
        migrations.AddIndex(
            model_name="affiliatecommission",
            index=models.Index(fields=["order", "created_at"], name="store_affil_order_i_5f1c0d_idx"),
        ),
    ]
