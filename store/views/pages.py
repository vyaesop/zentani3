"""Static policy and help pages (privacy, terms, FAQ) plus robots.txt."""
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET

from store.constants import ADDIS_FREE_SHIPPING_THRESHOLD, ADDIS_SHIPPING_FEE, OUTSIDE_ADDIS_SHIPPING_FEE


def _policy_context():
    return {
        "delivery_note": settings.STORE_DELIVERY_NOTE,
        "return_note": settings.STORE_RETURN_NOTE,
        "addis_fee": f"{ADDIS_SHIPPING_FEE:.0f}",
        "outside_fee": f"{OUTSIDE_ADDIS_SHIPPING_FEE:.0f}",
        "free_threshold": f"{ADDIS_FREE_SHIPPING_THRESHOLD:,.0f}",
        "ga_enabled": bool(getattr(settings, "GA_MEASUREMENT_ID", "")),
        "online_payments_enabled": getattr(settings, "ONLINE_PAYMENTS_ENABLED", False),
    }


def privacy(request):
    return render(request, "store/privacy.html", _policy_context())


def terms(request):
    return render(request, "store/terms.html", _policy_context())


def faq(request):
    return render(request, "store/faq.html", _policy_context())


@require_GET
def robots_txt(request):
    """Allow the catalog, keep private and transactional paths out of the index."""
    sitemap_url = request.build_absolute_uri(reverse("store:sitemap"))
    site_url = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
    if site_url:
        sitemap_url = f"{site_url}{reverse('store:sitemap')}"
    lines = [
        "User-agent: *",
        "Disallow: /admin/",
        "Disallow: /dashboard/",
        "Disallow: /internal/",
        "Disallow: /accounts/",
        "Disallow: /cart/",
        "Disallow: /checkout/",
        "Disallow: /orders/",
        "Disallow: /review/",
        "Disallow: /payments/",
        "Disallow: /add-to-cart/",
        "Disallow: /add-coupon/",
        "Disallow: /remove-cart/",
        "Disallow: /plus-cart/",
        "Disallow: /minus-cart/",
        "Disallow: /wishlist/",
        "Disallow: /telegram/",
        "Disallow: /ref/",
        "Disallow: /i18n/",
        "Disallow: /search/",
        "Allow: /",
        "",
        f"Sitemap: {sitemap_url}",
        "",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")
