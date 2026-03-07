from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("store", "0035_affiliate_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="affiliatecommission",
            name="paid_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="affiliatecommission",
            name="payout_note",
            field=models.CharField(blank=True, max_length=250),
        ),
        migrations.AddField(
            model_name="affiliatecommission",
            name="payout_reference",
            field=models.CharField(blank=True, max_length=120),
        ),
    ]
