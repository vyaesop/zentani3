"""Product feed for Google Merchant Center and Meta (Instagram/Facebook) catalogs.

RSS 2.0 with the `g:` namespace, one item per size so each variant can be
listed with its own availability; unsized products emit a single item.
"""
from django.conf import settings
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_GET

from store.constants import ADDIS_FREE_SHIPPING_THRESHOLD, ADDIS_SHIPPING_FEE, OUTSIDE_ADDIS_SHIPPING_FEE
from store.models import Product
from store.seo import clean_seo_copy


def _absolute(request, path):
    base = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
    if base:
        return f"{base}{path}"
    return request.build_absolute_uri(path)


def _image_url(request, image):
    if not image:
        return ""
    url = image.url
    if url.startswith("/"):
        return _absolute(request, url)
    return url


@require_GET
def google_merchant_feed(request):
    items = []
    products = (
        Product.objects.filter(is_active=True)
        .select_related("category", "brand")
        .prefetch_related("size_inventory", "p_images")
        .order_by("-updated_at")
    )
    for product in products:
        link = _absolute(request, reverse("store:product-detail", kwargs={"slug": product.slug}))
        description = clean_seo_copy(
            product.detail_description or product.short_description,
            fallback=product.title,
        )[:5000]
        base = {
            "title": clean_seo_copy(product.title, fallback=product.sku)[:150],
            "description": description,
            "link": link,
            "image_link": _image_url(request, product.product_image),
            "additional_images": [_image_url(request, image.image) for image in product.p_images.all()[:10] if image.image],
            "brand": product.brand.title if product.brand_id and product.brand.title.lower() != "no brand" else "",
            "product_type": product.category.title if product.category_id else "",
            "price": f"{product.price:.2f} ETB",
            "sale_price": f"{product.price:.2f} ETB" if product.is_on_sale else "",
            "regular_price": f"{product.compare_at_price:.2f} ETB" if product.is_on_sale else "",
            "color": product.color,
            "material": product.material,
            "group_id": product.sku,
        }
        sizes = list(product.size_inventory.all())
        if sizes:
            for row in sizes:
                items.append(
                    {
                        **base,
                        "id": f"{product.sku}-{row.size}".replace(" ", "-"),
                        "size": row.size,
                        "availability": "in stock" if row.quantity > 0 and not product.is_sold_out else "out of stock",
                    }
                )
        else:
            items.append(
                {
                    **base,
                    "id": product.sku,
                    "size": "",
                    "availability": "out of stock" if product.is_sold_out else "in stock",
                }
            )

    xml = render_to_string(
        "feeds/google_merchant.xml",
        {
            "store_name": settings.STORE_NAME,
            "site_url": _absolute(request, "/"),
            "items": items,
            "addis_fee": f"{ADDIS_SHIPPING_FEE:.2f}",
            "outside_fee": f"{OUTSIDE_ADDIS_SHIPPING_FEE:.2f}",
            "free_threshold": f"{ADDIS_FREE_SHIPPING_THRESHOLD:.2f}",
        },
        request=request,
    )
    return HttpResponse(xml, content_type="application/xml; charset=utf-8")
