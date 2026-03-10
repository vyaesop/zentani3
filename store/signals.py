from django.db.models.signals import post_save
from django.dispatch import receiver

from store.models import Product
from store.telegram_notify import post_product_to_channel


@receiver(post_save, sender=Product)
def post_new_product_to_telegram(sender, instance, created, **kwargs):
    # Only auto-post truly new active products.
    if not created:
        return
    if not instance.is_active or instance.is_sold_out:
        return
    post_product_to_channel(instance)
