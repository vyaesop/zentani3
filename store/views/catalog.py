"""Product pages: home, detail, wishlist, reviews, restock requests, review invites."""
import json
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from store.constants import (
    ADDIS_FREE_SHIPPING_THRESHOLD,
    ADDIS_SHIPPING_FEE,
    OUTSIDE_ADDIS_SHIPPING_FEE,
    RECENTLY_VIEWED_SESSION_KEY,
    size_sort_key as _size_sort_key,
)
from store.forms import InviteReviewForm, ProductReviewForm, RestockRequestForm
from store.models import (
    Brand,
    Category,
    Order,
    Product,
    ProductEvent,
    ProductReview,
    ProductSizeStock,
    RestockRequest,
    Wishlist,
)
from store.seo import clean_seo_copy

from .common import _is_htmx

PRODUCT_LIST_FIELDS = (
    "id",
    "slug",
    "title",
    "price",
    "compare_at_price",
    "created_at",
    "product_image",
    "is_sold_out",
    "color_group",
    "category__title",
    "category__slug",
    "brand__title",
    "brand__slug",
)


def _recently_viewed_product_ids(request):
    return [int(product_id) for product_id in request.session.get(RECENTLY_VIEWED_SESSION_KEY, []) if str(product_id).isdigit()]


def _push_recently_viewed_product(request, product):
    existing_ids = [product_id for product_id in _recently_viewed_product_ids(request) if product_id != product.id]
    request.session[RECENTLY_VIEWED_SESSION_KEY] = [product.id, *existing_ids][:8]
    request.session.modified = True


def _recently_viewed_products(request, exclude_id=None, limit=4):
    product_ids = [product_id for product_id in _recently_viewed_product_ids(request) if product_id != exclude_id]
    if not product_ids:
        return []

    products_by_id = {
        product.id: product
        for product in Product.objects.filter(id__in=product_ids, is_active=True)
        .select_related("category", "brand")
        .prefetch_related("size_inventory", "p_images")
        .only(*PRODUCT_LIST_FIELDS)
    }
    ordered_products = [products_by_id[product_id] for product_id in product_ids if product_id in products_by_id]
    return ordered_products[:limit]


def _saved_product_ids_for_user(user):
    if not getattr(user, "is_authenticated", False):
        return set()
    return set(Wishlist.objects.filter(user=user).values_list("product_id", flat=True))


CO_PURCHASE_CACHE_TTL = 6 * 60 * 60


def _co_purchase_product_ids(product, limit=4):
    """Ids of products most often bought by the same customers, cached."""
    from django.core.cache import cache
    from django.db.models import Count as _Count, Q as _Q

    cache_key = f"co_purchase_ids:{product.id}"
    product_ids = cache.get(cache_key)
    if product_ids is None:
        buyer_users = list(
            Order.objects.filter(product=product, user__isnull=False).values_list("user_id", flat=True).distinct()
        )
        buyer_sessions = list(
            Order.objects.filter(product=product, user=None)
            .exclude(session_key="")
            .values_list("session_key", flat=True)
            .distinct()
        )
        if not buyer_users and not buyer_sessions:
            product_ids = []
        else:
            buyer_query = _Q(user_id__in=buyer_users)
            if buyer_sessions:
                buyer_query |= _Q(session_key__in=buyer_sessions)
            product_ids = list(
                Order.objects.filter(buyer_query)
                .exclude(product=product)
                .filter(product__is_active=True)
                .values("product_id")
                .annotate(n=_Count("id"))
                .order_by("-n", "-product_id")
                .values_list("product_id", flat=True)[:limit]
            )
        cache.set(cache_key, product_ids, CO_PURCHASE_CACHE_TTL)
    return product_ids


def _related_products_for(product, limit=4):
    """Co-purchase picks first ("customers also bought"), same-category fill."""
    co_purchase_ids = _co_purchase_product_ids(product, limit=limit)
    products_by_id = {
        candidate.id: candidate
        for candidate in Product.objects.filter(id__in=co_purchase_ids, is_active=True)
        .select_related("category", "brand")
        .prefetch_related("size_inventory", "p_images")
        .only(*PRODUCT_LIST_FIELDS)
    }
    related = [products_by_id[pid] for pid in co_purchase_ids if pid in products_by_id]
    if len(related) < limit:
        fill = (
            Product.objects.filter(is_active=True, category=product.category)
            .exclude(id__in=[product.id, *[item.id for item in related]])
            .select_related("category", "brand")
            .prefetch_related("size_inventory", "p_images")
            .only(*PRODUCT_LIST_FIELDS)[: limit - len(related)]
        )
        related.extend(fill)
    return related


def _size_guide_lines(text):
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _build_product_detail_context(request, product):
    from store.services import color_variants
    from store.telegram_notify import product_order_deep_link

    related_products = _related_products_for(product)
    recently_viewed = _recently_viewed_products(request, exclude_id=product.id)
    # Shoppers only see live colours; the current product is always included.
    color_family = color_variants.color_family(product)
    p_image = product.p_images.only("id", "image").all()
    size_options = _product_size_options(product)
    available_sizes_list = [option["size"] for option in size_options]
    default_selected_size = next((option["size"] for option in size_options if option["available"]), "")
    reviews = list(
        ProductReview.objects.filter(product=product)
        .select_related("user")
        .only(
            "id", "rating", "title", "comment", "fit_feedback", "image", "created_at",
            "reviewer_name", "is_verified_purchase",
            "user__first_name", "user__last_name", "user__username",
        )[:6]
    )
    review_summary = ProductReview.objects.filter(product=product).aggregate(
        average_rating=Avg("rating"),
        review_count=Count("id"),
    )
    fit_counts = dict(
        ProductReview.objects.filter(product=product)
        .exclude(fit_feedback="")
        .values_list("fit_feedback")
        .annotate(n=Count("id"))
        .values_list("fit_feedback", "n")
    )
    fit_total = sum(fit_counts.values())
    fit_summary = None
    if fit_total:
        true_to_size = fit_counts.get(ProductReview.FIT_TRUE_TO_SIZE, 0)
        fit_summary = {
            "total": fit_total,
            "true_to_size_percent": int(round(true_to_size * 100 / fit_total)),
        }
    saved_product_ids = _saved_product_ids_for_user(request.user)
    existing_restock_request = None
    restock_initial = {}
    if request.user.is_authenticated:
        restock_initial["email"] = request.user.email or ""
        if product.is_sold_out:
            existing_restock_request = RestockRequest.objects.filter(product=product, user=request.user).first()

    size_guide_text = product.measurements or (product.category.size_guide if product.category_id else "")
    seo_title = _product_seo_title(product)
    seo_description = _product_seo_description(product)

    return {
        "product": product,
        "related_products": related_products,
        "p_image": p_image,
        "available_sizes": available_sizes_list,
        "size_options": size_options,
        "default_selected_size": default_selected_size,
        "reviews": reviews,
        "review_summary": review_summary,
        "fit_summary": fit_summary,
        "review_form": ProductReviewForm(),
        "restock_form": RestockRequestForm(initial=restock_initial),
        "existing_restock_request": existing_restock_request,
        "saved_product_ids": saved_product_ids,
        "is_saved_product": product.id in saved_product_ids,
        "recently_viewed_products": recently_viewed,
        "color_family": color_family,
        "color_counts": color_variants.color_count_map([*related_products, *recently_viewed]),
        "product_stock_message": _product_stock_message(product, size_value=default_selected_size or None),
        "product_delivery_note": product.delivery_note or settings.STORE_DELIVERY_NOTE,
        "product_return_note": product.return_note or settings.STORE_RETURN_NOTE,
        "is_cash_on_delivery_only": not getattr(settings, "ONLINE_PAYMENTS_ENABLED", False),
        "size_guide_lines": _size_guide_lines(size_guide_text),
        "size_guide_source": "product" if product.measurements else "collection",
        "telegram_order_url": product_order_deep_link(product),
        "seo_title": seo_title,
        "seo_description": seo_description,
        "seo_image_alt_text": _product_image_alt_text(product),
        "product_canonical_url": request.build_absolute_uri(reverse("store:product-detail", kwargs={"slug": product.slug})),
        "product_og_image_url": _product_og_image_url(request, product),
        "product_schema_json": json.dumps(_product_schema(request, product, p_image, available_sizes_list, review_summary)),
        "breadcrumb_schema_json": json.dumps(_breadcrumb_schema(request, product)),
        "ga_item_json": json.dumps(_ga_item(product)),
        "preview_hidden": not product.is_active,
    }


def _ga_item(product, quantity=1, size=""):
    item = {
        "item_id": product.sku,
        "item_name": product.title,
        "price": float(product.price or 0),
        "currency": "ETB",
        "quantity": quantity,
    }
    if product.category_id:
        item["item_category"] = product.category.title
    if product.brand_id:
        item["item_brand"] = product.brand.title
    if size:
        item["item_variant"] = size
    return item


def _product_seo_title(product):
    custom = clean_seo_copy(product.seo_title, fallback="")
    if custom:
        return custom
    parts = [product.title]
    if product.category_id:
        parts.append(product.category.title)
    parts.append(f"{settings.STORE_NAME} Ethiopia")
    return " | ".join(parts[:3])


def _product_seo_description(product):
    custom = clean_seo_copy(product.seo_description, fallback="")
    if custom:
        return custom[:320]
    details = [product.short_description or "", product.material or "", product.color or ""]
    summary = " ".join(part.strip() for part in details if part and part.strip()).strip()
    if not summary:
        summary = f"Shop {product.title} at {settings.STORE_NAME} Ethiopia. Cash on delivery in Addis Ababa."
    return clean_seo_copy(summary, fallback=f"Shop {product.title} at {settings.STORE_NAME}.")[:320]


def _product_image_alt_text(product):
    custom = clean_seo_copy(product.image_alt_text, fallback="")
    if custom:
        return custom
    descriptors = [product.color or "", product.title]
    return " ".join(part.strip() for part in descriptors if part and part.strip()).strip() or product.title


def _product_og_image_url(request, product):
    if not product.product_image:
        return ""
    url = product.product_image.url
    if url.startswith("/"):
        return request.build_absolute_uri(url)
    return url


def _shipping_details_schema():
    def _rate(value, region=None):
        destination = {"@type": "DefinedRegion", "addressCountry": "ET"}
        if region:
            destination["addressRegion"] = region
        return {
            "@type": "OfferShippingDetails",
            "shippingRate": {"@type": "MonetaryAmount", "value": f"{value:.0f}", "currency": "ETB"},
            "shippingDestination": destination,
            "deliveryTime": {
                "@type": "ShippingDeliveryTime",
                "handlingTime": {"@type": "QuantitativeValue", "minValue": 0, "maxValue": 1, "unitCode": "DAY"},
                "transitTime": {"@type": "QuantitativeValue", "minValue": 1, "maxValue": 3, "unitCode": "DAY"},
            },
        }

    addis = _rate(ADDIS_SHIPPING_FEE, region="Addis Ababa")
    addis["description"] = f"Free on orders over {ADDIS_FREE_SHIPPING_THRESHOLD:,.0f} ETB."
    return [addis, _rate(OUTSIDE_ADDIS_SHIPPING_FEE)]


def _return_policy_schema(product):
    return {
        "@type": "MerchantReturnPolicy",
        "applicableCountry": "ET",
        "returnPolicyCategory": "https://schema.org/MerchantReturnNotPermitted",
        "description": product.return_note or settings.STORE_RETURN_NOTE,
    }


def _product_schema(request, product, gallery_images, available_sizes, review_summary=None):
    image_urls = []
    for image in [product.product_image, *[item.image for item in gallery_images]]:
        if not image:
            continue
        url = image.url
        if url.startswith("/"):
            url = request.build_absolute_uri(url)
        image_urls.append(url)

    product_url = request.build_absolute_uri(reverse("store:product-detail", kwargs={"slug": product.slug}))
    schema = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": product.title,
        "description": _product_seo_description(product),
        "sku": product.sku,
        "category": product.category.title if product.category_id else "",
        "image": image_urls,
        "url": product_url,
        "brand": {
            "@type": "Brand",
            "name": product.brand.title if product.brand_id else settings.STORE_NAME,
        },
        "offers": {
            "@type": "Offer",
            "priceCurrency": "ETB",
            "price": str(product.price),
            "priceValidUntil": (timezone.now() + timedelta(days=30)).date().isoformat(),
            "itemCondition": "https://schema.org/NewCondition",
            "availability": (
                "https://schema.org/InStock"
                if product.is_active and not product.is_sold_out
                else "https://schema.org/OutOfStock"
            ),
            "url": product_url,
            "seller": {"@type": "Organization", "name": settings.STORE_NAME},
            "shippingDetails": _shipping_details_schema(),
            "hasMerchantReturnPolicy": _return_policy_schema(product),
        },
    }
    if available_sizes:
        schema["size"] = available_sizes
    if product.color:
        schema["color"] = product.color
    if product.material:
        schema["material"] = product.material
    if review_summary and review_summary.get("review_count"):
        schema["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": f"{float(review_summary['average_rating'] or 0):.1f}",
            "reviewCount": review_summary["review_count"],
            "bestRating": 5,
            "worstRating": 1,
        }
    return schema


def _breadcrumb_schema(request, product):
    items = [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": request.build_absolute_uri(reverse("store:home"))},
    ]
    if product.category_id:
        items.append(
            {
                "@type": "ListItem",
                "position": 2,
                "name": product.category.title,
                "item": request.build_absolute_uri(reverse("store:category-products", kwargs={"slug": product.category.slug})),
            }
        )
        product_position = 3
    else:
        product_position = 2
    items.append(
        {
            "@type": "ListItem",
            "position": product_position,
            "name": product.title,
            "item": request.build_absolute_uri(reverse("store:product-detail", kwargs={"slug": product.slug})),
        }
    )
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": items,
    }


def _organization_schema(request):
    base = (getattr(settings, "SITE_URL", "") or "").rstrip("/") or request.build_absolute_uri("/").rstrip("/")
    same_as = [url for url in [settings.STORE_INSTAGRAM_URL] if url]
    organization = {
        "@context": "https://schema.org",
        "@type": "OnlineStore",
        "name": settings.STORE_NAME,
        "url": f"{base}/",
        "logo": request.build_absolute_uri("/static/asset/images/logo-circle.png"),
        "telephone": settings.STORE_PHONE,
        "address": {"@type": "PostalAddress", "addressLocality": "Addis Ababa", "addressCountry": "ET"},
        "sameAs": same_as,
    }
    if settings.STORE_LEGAL_NAME:
        organization["legalName"] = settings.STORE_LEGAL_NAME
    if settings.STORE_EMAIL:
        organization["email"] = settings.STORE_EMAIL
    website = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": settings.STORE_NAME,
        "url": f"{base}/",
        "potentialAction": {
            "@type": "SearchAction",
            "target": {"@type": "EntryPoint", "urlTemplate": f"{base}/search/?q={{search_term_string}}"},
            "query-input": "required name=search_term_string",
        },
    }
    return [organization, website]


def _parse_available_sizes(product):
    if not product.available_sizes:
        return []
    return [size.strip() for size in product.available_sizes.split(",") if size.strip()]


def _size_inventory_queryset(product):
    return ProductSizeStock.objects.filter(product=product)


def _size_inventory_map(product):
    return {
        item.size.strip(): item.quantity
        for item in _size_inventory_queryset(product).only("size", "quantity")
        if item.size and item.size.strip()
    }


def _stock_label(quantity, sold_out=False):
    """Copy for a given unit count, honouring STORE_SHOW_STOCK_COUNTS."""
    if sold_out or (quantity is not None and quantity <= 0):
        return "Currently sold out"
    if quantity is None:
        return "In stock"
    if getattr(settings, "STORE_SHOW_STOCK_COUNTS", False):
        if quantity <= 3:
            return f"Only {quantity} left"
        return f"{quantity} in stock"
    if quantity <= 3:
        return "In stock · only a few left"
    return "In stock · 1-3 day delivery in Addis"


def _product_size_options(product):
    inventory = _size_inventory_map(product)
    if inventory:
        return [
            {
                "size": size,
                "quantity": quantity,
                "available": quantity > 0,
                "stock_label": _stock_label(quantity),
            }
            for size, quantity in sorted(inventory.items(), key=lambda item: _size_sort_key(item[0]))
        ]

    return [
        {
            "size": size,
            "quantity": None,
            "available": not product.is_sold_out,
            "stock_label": _stock_label(None, sold_out=product.is_sold_out),
        }
        for size in _parse_available_sizes(product)
    ]


def _product_size_stock(product, size_value=None):
    inventory = _size_inventory_map(product)
    if inventory:
        if size_value:
            return inventory.get(size_value, 0)
        return sum(inventory.values())

    return product.stock_quantity


def _product_can_fulfill_quantity(product, requested_quantity, size_value=None):
    if requested_quantity <= 0:
        return False
    available_quantity = _product_size_stock(product, size_value=size_value)
    if available_quantity <= 0:
        return False
    return requested_quantity <= available_quantity


def _product_stock_message(product, size_value=None):
    available_quantity = _product_size_stock(product, size_value=size_value)
    return _stock_label(available_quantity, sold_out=product.is_sold_out)


def _live_count_annotation():
    return Count("product", filter=Q(product__is_active=True))


def home(request):
    # Only feature collections/brands that have something live behind them — a
    # spotlight band that lands on an empty page is a dead end.
    categories = list(
        Category.objects.filter(is_active=True, is_featured=True)
        .annotate(live_count=_live_count_annotation())
        .filter(live_count__gt=0)
        .only("id", "title", "slug", "category_image", "description")
        .order_by("-created_at")[:8]
    )
    brands = list(
        Brand.objects.filter(is_active=True, is_featured=True)
        .annotate(live_count=_live_count_annotation())
        .filter(live_count__gt=0)
        .only("id", "title", "slug", "brand_image", "description")
        .order_by("-created_at")[:12]
    )
    products = Product.objects.filter(is_active=True, is_featured=True).select_related("category", "brand").prefetch_related("size_inventory", "p_images").only(*PRODUCT_LIST_FIELDS)[:24]
    latest_products = list(
        Product.objects.filter(is_active=True)
        .select_related("category", "brand")
        .prefetch_related("size_inventory", "p_images")
        .only(*PRODUCT_LIST_FIELDS)
        .order_by("-created_at")[:8]
    )
    # The hero shows the three newest pieces; "The drop" continues with the next
    # five so nothing on the page repeats itself. The five-module rhythm (one
    # lead, four supporting) is what the homepage grid is built for.
    hero_products = latest_products[:3]
    drop_products = latest_products[3:8]
    latest_drop_date = None
    if latest_products and latest_products[0].created_at:
        newest = latest_products[0].created_at
        if newest >= timezone.now() - timedelta(days=30):
            latest_drop_date = newest
    live_product_count = Product.objects.filter(is_active=True).count()
    from store.context_preprocessors import top_selling_product_ids

    top_selling_ids = top_selling_product_ids()
    top_selling_lookup = {
        product.id: product
        for product in Product.objects.filter(id__in=top_selling_ids, is_active=True)
        .select_related("category", "brand")
        .prefetch_related("size_inventory", "p_images")
        .only(*PRODUCT_LIST_FIELDS)
    }
    top_selling_products = [top_selling_lookup[product_id] for product_id in top_selling_ids if product_id in top_selling_lookup][:5]
    # Editorial bands: first featured collection/brand that has imagery.
    story_category = next((category for category in categories if category.category_image), None)
    spotlight_brand = next((brand for brand in brands if brand.brand_image), None)

    from store.services import color_variants

    recently_viewed = _recently_viewed_products(request, limit=4)
    context = {
        "categories": categories,
        "products": products,
        "brands": brands,
        "latest_products": latest_products,
        "hero_products": hero_products,
        "drop_products": drop_products,
        "latest_drop_date": latest_drop_date,
        "live_product_count": live_product_count,
        "top_selling_products": top_selling_products,
        "story_category": story_category,
        "spotlight_brand": spotlight_brand,
        "recently_viewed_products": recently_viewed,
        "color_counts": color_variants.color_count_map(
            [*products, *latest_products, *hero_products, *drop_products, *top_selling_products, *recently_viewed]
        ),
        "saved_product_ids": _saved_product_ids_for_user(request.user),
        "organization_schema_json": json.dumps(_organization_schema(request)),
    }
    return render(request, "store/index.html", context)


def _render_unavailable(request, product):
    """Hidden/retired product: a helpful 404 rather than a buyable-looking page.

    Search engines get a real 404 + noindex so the URL drops out of the index;
    shoppers arriving from an old Telegram post get the collection and a few
    live alternatives instead of a dead add-to-cart button.
    """
    alternatives = list(
        Product.objects.filter(is_active=True, category=product.category)
        .exclude(id=product.id)
        .select_related("category", "brand")
        .prefetch_related("size_inventory", "p_images")
        .only(*PRODUCT_LIST_FIELDS)[:4]
    )
    if len(alternatives) < 4:
        fill = (
            Product.objects.filter(is_active=True)
            .exclude(id__in=[product.id, *[item.id for item in alternatives]])
            .select_related("category", "brand")
            .prefetch_related("size_inventory", "p_images")
            .only(*PRODUCT_LIST_FIELDS)
            .order_by("-created_at")[: 4 - len(alternatives)]
        )
        alternatives.extend(fill)
    response = render(
        request,
        "store/product_unavailable.html",
        {
            "product": product,
            "alternatives": alternatives,
            "saved_product_ids": _saved_product_ids_for_user(request.user),
            "robots_meta": "noindex, follow",
        },
        status=404,
    )
    return response


def detail(request, slug):
    product = get_object_or_404(
        Product.objects.select_related("category", "brand"),
        slug=slug,
    )
    if not product.is_active and not request.user.is_staff:
        return _render_unavailable(request, product)
    if product.is_active:
        _push_recently_viewed_product(request, product)
        ProductEvent.log(ProductEvent.EVENT_VIEW, product, request=request)
    context = _build_product_detail_context(request, product)
    if not product.is_active:
        context["robots_meta"] = "noindex, nofollow"
    return render(request, "store/detail.html", context)


@login_required
def toggle_wishlist(request, product_id):
    if request.method != "POST":
        messages.warning(request, "Invalid save action.")
        return redirect("store:product-detail", slug=get_object_or_404(Product, id=product_id).slug)

    product = get_object_or_404(Product, id=product_id, is_active=True)
    wishlist_entry = Wishlist.objects.filter(user=request.user, product=product).first()

    if wishlist_entry:
        wishlist_entry.delete()
        saved = False
        message = f"Removed {product.title} from your saved items."
    else:
        Wishlist.objects.create(user=request.user, product=product)
        saved = True
        message = f"Saved {product.title} for later."

    if _is_htmx(request):
        return render(
            request,
            "store/_wishlist_button.html",
            {"product": product, "saved": saved, "variant": request.POST.get("variant", "")},
        )

    messages.success(request, message)
    return redirect(request.POST.get("next") or reverse("store:product-detail", kwargs={"slug": product.slug}))


@login_required
def submit_review(request, slug):
    product = get_object_or_404(Product, slug=slug, is_active=True)
    if request.method != "POST":
        return redirect("store:product-detail", slug=product.slug)

    form = ProductReviewForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "Please complete the review fields before submitting.")
        return redirect(f"{reverse('store:product-detail', kwargs={'slug': product.slug})}#reviews")

    defaults = dict(form.cleaned_data)
    # A re-submitted review only touches the photo when one was uploaded (or
    # explicitly cleared via the form's clear checkbox, which yields False).
    image_value = defaults.pop("image", None)
    defaults["is_verified_purchase"] = Order.objects.filter(
        user=request.user, product=product, status="Delivered"
    ).exists()
    review, _ = ProductReview.objects.update_or_create(
        user=request.user,
        product=product,
        defaults=defaults,
    )
    if image_value is False:
        review.image = None
        review.save(update_fields=["image", "updated_at"])
    elif image_value:
        review.image = image_value
        review.save(update_fields=["image", "updated_at"])
    messages.success(request, "Your review has been saved.")
    return redirect(f"{reverse('store:product-detail', kwargs={'slug': product.slug})}#reviews")


def review_invite(request, token):
    """Tokenised review form sent to buyers of a delivered order line.

    No login needed: the token proves the purchase, and the review is stamped
    as a verified purchase. Signed-in customers who already reviewed the
    product through their account simply edit that review.
    """
    order = get_object_or_404(
        Order.objects.select_related("product", "product__category", "product__brand", "group", "user"),
        review_token=token,
        status="Delivered",
    )
    if not token:
        return redirect("store:home")
    product = order.product

    existing = ProductReview.objects.filter(order=order).first()
    if existing is None and order.user_id:
        existing = ProductReview.objects.filter(user=order.user, product=product).first()

    if request.method == "POST":
        form = InviteReviewForm(request.POST, request.FILES, instance=existing)
        if form.is_valid():
            review = form.save(commit=False)
            review.product = product
            review.order = order
            review.user = order.user
            review.is_verified_purchase = True
            if not review.reviewer_name:
                review.reviewer_name = (order.customer_name or "Verified buyer").split()[0]
            review.save()
            messages.success(request, "Thank you — your review is live and marked as a verified purchase.")
            return redirect(f"{reverse('store:product-detail', kwargs={'slug': product.slug})}#reviews")
        messages.error(request, "Please complete the review fields before submitting.")
    else:
        initial = {}
        if existing is None:
            initial["reviewer_name"] = (order.customer_name or "").split()[0] if order.customer_name else ""
        form = InviteReviewForm(instance=existing, initial=initial)

    return render(
        request,
        "store/review_invite.html",
        {
            "order": order,
            "product": product,
            "form": form,
            "existing_review": existing,
            "robots_meta": "noindex, nofollow",
        },
    )


def request_restock(request, slug):
    product = get_object_or_404(Product, slug=slug, is_active=True)
    if request.method != "POST":
        return redirect("store:product-detail", slug=product.slug)

    form = RestockRequestForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Please enter a valid email address to join the restock list.")
        return redirect(f"{reverse('store:product-detail', kwargs={'slug': product.slug})}#restock")

    payload = form.cleaned_data
    defaults = {}
    if request.user.is_authenticated:
        defaults["user"] = request.user
    restock_request, created = RestockRequest.objects.get_or_create(
        product=product,
        email=payload["email"],
        size=payload["size"],
        defaults=defaults,
    )
    if not created and request.user.is_authenticated and restock_request.user_id is None:
        restock_request.user = request.user
        restock_request.save(update_fields=["user"])

    if created:
        messages.success(request, "You are on the restock list for this product.")
    else:
        messages.info(request, "You are already on the restock list for this product.")
    return redirect(f"{reverse('store:product-detail', kwargs={'slug': product.slug})}#restock")


def shop(request):
    return redirect("store:all-products")


def service_worker(request):
    """Serve the PWA service worker from the site root so its scope is '/'."""
    return render(request, "sw.js", content_type="application/javascript")


def delivery_returns(request):
    return render(
        request,
        "store/delivery-returns.html",
        {
            "delivery_note": settings.STORE_DELIVERY_NOTE,
            "return_note": settings.STORE_RETURN_NOTE,
            "addis_fee": f"{ADDIS_SHIPPING_FEE:.0f}",
            "outside_fee": f"{OUTSIDE_ADDIS_SHIPPING_FEE:.0f}",
            "free_threshold": f"{ADDIS_FREE_SHIPPING_THRESHOLD:,.0f}",
        },
    )


def about(request):
    return render(request, "store/about-us.html")


def contact(request):
    return render(request, "store/contact.html")


def test(request):
    return redirect("store:home")
