# Generated by Django 4.2.7 on 2024-03-25 19:52

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0022_alter_coupon_code'),
    ]

    operations = [
        migrations.AlterField(
            model_name='coupon',
            name='code',
            field=models.TextField(default=None, max_length=30, unique=True),
        ),
    ]