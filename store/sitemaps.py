"""XML sitemaps for the storefront (products, collections, brands, pages)."""
from django.conf import settings
from django.contrib.sitemaps import Sitemap
from django.db.models import Count, Q
from django.urls import reverse

from .models import Brand, Category, Product


class _StoreSitemap(Sitemap):
    protocol = "http" if settings.DEBUG else "https"

    def get_domain(self, site=None):
        # Prefer the configured canonical host over whatever host the crawler
        # used (Vercel preview URLs, www vs bare domain).
        site_url = (getattr(settings, "SITE_URL", "") or "").strip()
        if site_url:
            host = site_url.split("://", 1)[-1].rstrip("/")
            return host
        return super().get_domain(site)


class ProductSitemap(_StoreSitemap):
    changefreq = "daily"
    priority = 0.8

    def items(self):
        return Product.objects.filter(is_active=True).only("slug", "updated_at").order_by("-updated_at")

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        return reverse("store:product-detail", kwargs={"slug": obj.slug})


class CategorySitemap(_StoreSitemap):
    changefreq = "weekly"
    priority = 0.6

    def items(self):
        return (
            Category.objects.filter(is_active=True)
            .annotate(live_count=Count("product", filter=Q(product__is_active=True)))
            .filter(live_count__gt=0)
            .only("slug", "updated_at")
            .order_by("title")
        )

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        return reverse("store:category-products", kwargs={"slug": obj.slug})


class BrandSitemap(_StoreSitemap):
    changefreq = "weekly"
    priority = 0.5

    def items(self):
        return (
            Brand.objects.filter(is_active=True)
            .annotate(live_count=Count("product", filter=Q(product__is_active=True)))
            .filter(live_count__gt=0)
            .only("slug", "updated_at")
            .order_by("title")
        )

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        return reverse("store:brand-products", kwargs={"slug": obj.slug})


class StaticViewSitemap(_StoreSitemap):
    changefreq = "monthly"
    priority = 0.4

    def items(self):
        return [
            "store:home",
            "store:all-products",
            "store:sale-products",
            "store:all-categories",
            "store:all-brands",
            "store:about",
            "store:contact",
            "store:delivery-returns",
            "store:faq",
            "store:privacy",
            "store:terms",
        ]

    def location(self, item):
        return reverse(item)

    def priority_for(self, item):
        return 1.0 if item == "store:home" else self.priority


SITEMAPS = {
    "pages": StaticViewSitemap,
    "products": ProductSitemap,
    "collections": CategorySitemap,
    "brands": BrandSitemap,
}
