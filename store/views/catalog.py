"""Product pages: home, detail, wishlist, reviews, and restock requests."""
import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from store.constants import RECENTLY_VIEWED_SESSION_KEY, size_sort_key as _size_sort_key
from store.forms import ProductReviewForm, RestockRequestForm
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


def _build_product_detail_context(request, product):
    related_products = _related_products_for(product)
    p_image = product.p_images.only("id", "image").all()
    size_options = _product_size_options(product)
    available_sizes_list = [option["size"] for option in size_options]
    default_selected_size = next((option["size"] for option in size_options if option["available"]), "")
    reviews = list(
        ProductReview.objects.filter(product=product)
        .select_related("user")
        .only(
            "id", "rating", "title", "comment", "fit_feedback", "image", "created_at",
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
        "recently_viewed_products": _recently_viewed_products(request, exclude_id=product.id),
        "product_stock_message": _product_stock_message(product, size_value=default_selected_size or None),
        "product_delivery_note": product.delivery_note or settings.STORE_DELIVERY_NOTE,
        "product_return_note": product.return_note or settings.STORE_RETURN_NOTE,
        "is_cash_on_delivery_only": True,
        "seo_title": _product_seo_title(product),
        "seo_description": _product_seo_description(product),
        "seo_image_alt_text": _product_image_alt_text(product),
        "product_canonical_url": request.build_absolute_uri(reverse("store:product-detail", kwargs={"slug": product.slug})),
        "product_og_image_url": _product_og_image_url(request, product),
        "product_schema_json": json.dumps(_product_schema(request, product, p_image, available_sizes_list)),
        "breadcrumb_schema_json": json.dumps(_breadcrumb_schema(request, product)),
    }


def _product_seo_title(product):
    if product.seo_title:
        return product.seo_title
    parts = [product.title]
    if product.category_id:
        parts.append(product.category.title)
    parts.append("Zentanee Ethiopia")
    return " | ".join(parts[:3])


def _product_seo_description(product):
    if product.seo_description:
        return product.seo_description
    details = [product.short_description or "", product.material or "", product.color or ""]
    summary = " ".join(part.strip() for part in details if part and part.strip()).strip()
    if not summary:
        summary = f"Shop {product.title} at Zentanee Ethiopia."
    return summary[:320]


def _product_image_alt_text(product):
    if product.image_alt_text:
        return product.image_alt_text
    descriptors = [product.color or "", product.title]
    return " ".join(part.strip() for part in descriptors if part and part.strip()).strip() or product.title


def _product_og_image_url(request, product):
    if not product.product_image:
        return ""
    url = product.product_image.url
    if url.startswith("/"):
        return request.build_absolute_uri(url)
    return url


def _product_schema(request, product, gallery_images, available_sizes):
    image_urls = []
    for image in [product.product_image, *[item.image for item in gallery_images]]:
        if not image:
            continue
        url = image.url
        if url.startswith("/"):
            url = request.build_absolute_uri(url)
        image_urls.append(url)

    schema = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": product.title,
        "description": _product_seo_description(product),
        "sku": product.sku,
        "category": product.category.title if product.category_id else "",
        "image": image_urls,
        "url": request.build_absolute_uri(reverse("store:product-detail", kwargs={"slug": product.slug})),
        "brand": {
            "@type": "Brand",
            "name": product.brand.title if product.brand_id else "Zentanee",
        },
        "offers": {
            "@type": "Offer",
            "priceCurrency": "ETB",
            "price": str(product.price),
            "availability": "https://schema.org/InStock" if not product.is_sold_out else "https://schema.org/OutOfStock",
            "url": request.build_absolute_uri(reverse("store:product-detail", kwargs={"slug": product.slug})),
        },
    }
    if available_sizes:
        schema["size"] = available_sizes
    if product.color:
        schema["color"] = product.color
    if product.material:
        schema["material"] = product.material
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


def _product_size_options(product):
    inventory = _size_inventory_map(product)
    if inventory:
        return [
            {
                "size": size,
                "quantity": quantity,
                "available": quantity > 0,
            }
            for size, quantity in sorted(inventory.items(), key=lambda item: _size_sort_key(item[0]))
        ]

    return [
        {
            "size": size,
            "quantity": None,
            "available": not product.is_sold_out,
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
    if product.is_sold_out or available_quantity <= 0:
        return "Currently sold out"
    if available_quantity <= 3:
        return f"Only {available_quantity} left"
    return f"{available_quantity} in stock"


def home(request):
    categories = Category.objects.filter(is_active=True, is_featured=True).only("id", "title", "slug", "category_image", "description").order_by("-created_at")[:8]
    brands = Brand.objects.filter(is_active=True, is_featured=True).only("id", "title", "slug", "brand_image", "description").order_by("-created_at")[:12]
    products = Product.objects.filter(is_active=True, is_featured=True).select_related("category", "brand").prefetch_related("size_inventory", "p_images").only(*PRODUCT_LIST_FIELDS)[:24]
    latest_products = Product.objects.filter(is_active=True).select_related("category", "brand").prefetch_related("size_inventory", "p_images").only(*PRODUCT_LIST_FIELDS).order_by("-created_at")[:8]
    from store.context_preprocessors import top_selling_product_ids

    top_selling_ids = top_selling_product_ids()
    top_selling_lookup = {
        product.id: product
        for product in Product.objects.filter(id__in=top_selling_ids, is_active=True)
        .select_related("category", "brand")
        .prefetch_related("size_inventory", "p_images")
        .only(*PRODUCT_LIST_FIELDS)
    }
    top_selling_products = [top_selling_lookup[product_id] for product_id in top_selling_ids if product_id in top_selling_lookup]
    # Editorial bands: first featured collection/brand that has imagery.
    story_category = next((category for category in categories if category.category_image), None)
    spotlight_brand = next((brand for brand in brands if brand.brand_image), None)

    context = {
        "categories": categories,
        "products": products,
        "brands": brands,
        "latest_products": latest_products,
        "top_selling_products": top_selling_products,
        "story_category": story_category,
        "spotlight_brand": spotlight_brand,
        "recently_viewed_products": _recently_viewed_products(request, limit=4),
        "saved_product_ids": _saved_product_ids_for_user(request.user),
    }
    return render(request, "store/index.html", context)


def detail(request, slug):
    product = get_object_or_404(
        Product.objects.select_related("category", "brand"),
        slug=slug,
    )
    _push_recently_viewed_product(request, product)
    ProductEvent.log(ProductEvent.EVENT_VIEW, product, request=request)
    context = _build_product_detail_context(request, product)
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
    from store.constants import (
        ADDIS_FREE_SHIPPING_THRESHOLD,
        ADDIS_SHIPPING_FEE,
        OUTSIDE_ADDIS_SHIPPING_FEE,
    )

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
