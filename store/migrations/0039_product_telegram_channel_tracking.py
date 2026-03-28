from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("store", "0038_auto_20260310_1703"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="telegram_channel_last_post_signature",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="product",
            name="telegram_channel_last_posted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
