from django.db.models.signals import post_save
from django.dispatch import receiver

from store.models import Product, ProductImages
from store.telegram_notify import post_product_to_channel


@receiver(post_save, sender=Product)
def post_product_to_telegram(sender, instance, **kwargs):
    if not instance.is_active or instance.is_sold_out:
        return
    post_product_to_channel(instance)


@receiver(post_save, sender=ProductImages)
def post_product_gallery_update_to_telegram(sender, instance, created, **kwargs):
    if not created or not instance.product:
        return
    product = instance.product
    if not product.is_active or product.is_sold_out:
        return
    post_product_to_channel(product)
