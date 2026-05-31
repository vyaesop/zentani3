from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0046_auto_20260418_0956'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='staff_notes',
            field=models.TextField(blank=True, help_text='Internal notes visible only to staff (address changes, delivery instructions, etc.)', verbose_name='Staff Notes'),
        ),
        migrations.AddField(
            model_name='coupon',
            name='used_count',
            field=models.PositiveIntegerField(default=0, editable=False, verbose_name='Times Used'),
        ),
        migrations.AddField(
            model_name='coupon',
            name='max_uses',
            field=models.PositiveIntegerField(blank=True, help_text='Leave blank for unlimited.', null=True, verbose_name='Max Uses'),
        ),
    ]
