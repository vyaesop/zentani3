from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from store.cache_utils import bump_catalog_version, invalidate_menus
from store.models import BackgroundTask, Brand, Category, Product, ProductImages, ProductSizeStock
from store.tasks import enqueue
from store.telegram_notify import telegram_autopublish_suspended


def _enqueue_product_post(product):
    enqueue(BackgroundTask.TYPE_TELEGRAM_PRODUCT_POST, {"product_id": product.id})


@receiver(post_save, sender=Category)
@receiver(post_delete, sender=Category)
@receiver(post_save, sender=Brand)
@receiver(post_delete, sender=Brand)
def invalidate_menu_caches(sender, **kwargs):
    invalidate_menus()
    bump_catalog_version()


@receiver(post_save, sender=Product)
@receiver(post_delete, sender=Product)
@receiver(post_save, sender=ProductSizeStock)
@receiver(post_delete, sender=ProductSizeStock)
def invalidate_catalog_caches(sender, **kwargs):
    bump_catalog_version()


@receiver(post_save, sender=Product)
def post_product_to_telegram(sender, instance, **kwargs):
    if telegram_autopublish_suspended():
        return
    if not instance.is_active or instance.is_sold_out:
        return
    _enqueue_product_post(instance)


@receiver(post_save, sender=ProductImages)
def post_product_gallery_update_to_telegram(sender, instance, created, **kwargs):
    if telegram_autopublish_suspended():
        return
    if not created or not instance.product:
        return
    product = instance.product
    if not product.is_active or product.is_sold_out:
        return
    _enqueue_product_post(product)
