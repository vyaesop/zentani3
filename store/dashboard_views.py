from datetime import timedelta
from decimal import Decimal
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .dashboard_forms import (
    DashboardProductForm,
    ProductImageFormSet,
    ProductSizeStockFormSet,
    decorate_dashboard_formset,
)
from .models import (
    STATUS_CHOICES,
    AffiliateCommission,
    Category,
    Order,
    Product,
    ProductReview,
    RestockRequest,
    TelegramBotOrder,
)
from .telegram_notify import (
    notify_customer_delivery_status,
    post_product_to_channel,
    suspend_telegram_autopublish,
)


STATUS_VALUES = {value for value, _ in STATUS_CHOICES}


def staff_required(view_func):
    @wraps(view_func)
    @login_required(login_url="store:login")
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_staff:
            messages.error(request, "Staff access is required to open the Zentanee control room.")
            return redirect("store:home")
        return view_func(request, *args, **kwargs)

    return _wrapped


def _dashboard_context(request, *, section, title, intro, **extra):
    context = {
        "dashboard_section": section,
        "dashboard_page_title": title,
        "dashboard_page_intro": intro,
        "dashboard_today": timezone.now(),
        "status_choices": STATUS_CHOICES,
        "legacy_admin_url": reverse("admin:index"),
        "storefront_url": reverse("store:home"),
    }
    context.update(extra)
    return context


def _query_string_without(request, *keys):
    params = request.GET.copy()
    for key in keys:
        params.pop(key, None)
    encoded = params.urlencode()
    return f"?{encoded}" if encoded else ""


def _absolute_affiliate_pattern(product):
    next_path = f"/product/{product.slug}/"
    relative = f"/ref/{{affiliate_code}}/?next={next_path}"
    site_url = getattr(settings, "SITE_URL", "").rstrip("/")
    if site_url:
        return {
            "relative": relative,
            "absolute": f"{site_url}{relative}",
        }
    return {"relative": relative, "absolute": ""}


@staff_required
def dashboard_home(request):
    now = timezone.now()
    last_seven_days = now - timedelta(days=7)

    product_stats = Product.objects.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(is_active=True)),
        featured=Count("id", filter=Q(is_featured=True)),
        sold_out=Count("id", filter=Q(is_sold_out=True)),
    )
    order_stats = Order.objects.aggregate(
        total=Count("id"),
        pending=Count("id", filter=Q(status="Pending")),
        delivered=Count("id", filter=Q(status="Delivered")),
        weekly=Count("id", filter=Q(ordered_date__gte=last_seven_days)),
        revenue=Coalesce(Sum("line_total"), Decimal("0.00")),
    )
    telegram_stats = TelegramBotOrder.objects.aggregate(
        total=Count("id"),
        pending=Count("id", filter=Q(status="Pending")),
        active=Count("id", filter=~Q(status__in=["Delivered", "Cancelled"])),
    )
    affiliate_stats = AffiliateCommission.objects.aggregate(
        pending=Coalesce(Sum("amount", filter=Q(status="Pending")), Decimal("0.00")),
        paid=Coalesce(Sum("amount", filter=Q(status="Paid")), Decimal("0.00")),
    )

    top_products = (
        Product.objects.filter(is_active=True)
        .annotate(order_volume=Count("order"))
        .filter(order_volume__gt=0)
        .select_related("category", "brand")
        .order_by("-order_volume", "-updated_at")[:5]
    )
    low_stock_products = (
        Product.objects.filter(is_active=True)
        .select_related("category", "brand")
        .filter(Q(stock_quantity__lte=3) | Q(is_sold_out=True))
        .order_by("is_sold_out", "stock_quantity", "title")[:6]
    )
    recent_orders = (
        Order.objects.select_related("user", "product")
        .order_by("-ordered_date")[:7]
    )
    recent_telegram_orders = (
        TelegramBotOrder.objects.select_related("product")
        .order_by("-created_at")[:7]
    )
    latest_reviews = (
        ProductReview.objects.select_related("product", "user")
        .order_by("-created_at")[:4]
    )
    latest_restock_requests = (
        RestockRequest.objects.select_related("product", "user")
        .order_by("-created_at")[:4]
    )

    context = _dashboard_context(
        request,
        section="overview",
        title="Control Room",
        intro="A faster operational view for orders, merchandising, inventory, and Telegram commerce.",
        product_stats=product_stats,
        order_stats=order_stats,
        telegram_stats=telegram_stats,
        affiliate_stats=affiliate_stats,
        top_products=top_products,
        low_stock_products=low_stock_products,
        recent_orders=recent_orders,
        recent_telegram_orders=recent_telegram_orders,
        latest_reviews=latest_reviews,
        latest_restock_requests=latest_restock_requests,
    )
    return render(request, "dashboard/overview.html", context)


@staff_required
def dashboard_orders(request):
    if request.method == "POST":
        order = get_object_or_404(Order, pk=request.POST.get("order_id"))
        new_status = (request.POST.get("status") or "").strip()
        if new_status not in STATUS_VALUES:
            messages.error(request, "That order status is not valid.")
            return redirect(request.POST.get("next") or reverse("store:dashboard-orders"))

        if order.status != new_status:
            order.status = new_status
            order.save(update_fields=["status"])
            messages.success(request, f"Order #{order.id} moved to {new_status}.")
        else:
            messages.info(request, f"Order #{order.id} is already marked as {new_status}.")
        return redirect(request.POST.get("next") or reverse("store:dashboard-orders"))

    query = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()

    orders = Order.objects.select_related("user", "product").order_by("-ordered_date")
    if status in STATUS_VALUES:
        orders = orders.filter(status=status)
    if query:
        query_filter = (
            Q(product__title__icontains=query)
            | Q(product__sku__icontains=query)
            | Q(user__username__icontains=query)
            | Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
            | Q(user__email__icontains=query)
        )
        if query.isdigit():
            query_filter |= Q(id=int(query))
        orders = orders.filter(query_filter)

    summary = orders.aggregate(
        total=Count("id"),
        pending=Count("id", filter=Q(status="Pending")),
        in_transit=Count("id", filter=Q(status__in=["Accepted", "Packed", "On The Way"])),
        delivered=Count("id", filter=Q(status="Delivered")),
        cancelled=Count("id", filter=Q(status="Cancelled")),
        revenue=Coalesce(Sum("line_total"), Decimal("0.00")),
    )

    paginator = Paginator(orders, 18)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = _dashboard_context(
        request,
        section="orders",
        title="Orders",
        intro="Filter, search, and move every storefront order through fulfillment without wading through generic admin rows.",
        orders=page_obj,
        order_summary=summary,
        filters={"q": query, "status": status},
        query_string_without_page=_query_string_without(request, "page"),
    )
    return render(request, "dashboard/orders.html", context)


@staff_required
def dashboard_telegram_orders(request):
    if request.method == "POST":
        telegram_order = get_object_or_404(TelegramBotOrder, pk=request.POST.get("order_id"))
        new_status = (request.POST.get("status") or "").strip()
        if new_status not in STATUS_VALUES:
            messages.error(request, "That Telegram order status is not valid.")
            return redirect(request.POST.get("next") or reverse("store:dashboard-telegram-orders"))

        previous_status = telegram_order.status
        if previous_status != new_status:
            telegram_order.status = new_status
            telegram_order.save(update_fields=["status", "updated_at"])
            delivered = notify_customer_delivery_status(telegram_order)
            if delivered:
                messages.success(
                    request,
                    f"Telegram order TG-{telegram_order.id} updated to {new_status} and the customer was notified.",
                )
            else:
                messages.warning(
                    request,
                    f"Telegram order TG-{telegram_order.id} updated to {new_status}, but the customer notification did not send.",
                )
        else:
            messages.info(request, f"Telegram order TG-{telegram_order.id} is already marked as {new_status}.")
        return redirect(request.POST.get("next") or reverse("store:dashboard-telegram-orders"))

    query = (request.GET.get("q") or "").strip()
    status = (request.GET.get("status") or "").strip()
    city = (request.GET.get("city") or "").strip()

    telegram_orders = TelegramBotOrder.objects.select_related("product").order_by("-created_at")
    if status in STATUS_VALUES:
        telegram_orders = telegram_orders.filter(status=status)
    if city:
        telegram_orders = telegram_orders.filter(customer_city__icontains=city)
    if query:
        query_filter = (
            Q(product_title__icontains=query)
            | Q(product_sku__icontains=query)
            | Q(customer_full_name__icontains=query)
            | Q(customer_phone__icontains=query)
            | Q(customer_address__icontains=query)
            | Q(telegram_username__icontains=query)
            | Q(telegram_chat_id__icontains=query)
        )
        if query.isdigit():
            query_filter |= Q(id=int(query))
        telegram_orders = telegram_orders.filter(query_filter)

    summary = telegram_orders.aggregate(
        total=Count("id"),
        pending=Count("id", filter=Q(status="Pending")),
        active=Count("id", filter=Q(status__in=["Accepted", "Packed", "On The Way"])),
        delivered=Count("id", filter=Q(status="Delivered")),
        cancelled=Count("id", filter=Q(status="Cancelled")),
    )

    paginator = Paginator(telegram_orders, 18)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = _dashboard_context(
        request,
        section="telegram",
        title="Telegram Orders",
        intro="Handle chat-originated leads with customer details, delivery status changes, and queue visibility in one place.",
        telegram_orders=page_obj,
        telegram_summary=summary,
        filters={"q": query, "status": status, "city": city},
        query_string_without_page=_query_string_without(request, "page"),
    )
    return render(request, "dashboard/telegram_orders.html", context)


@staff_required
def dashboard_products(request):
    if request.method == "POST":
        product = get_object_or_404(Product.objects.select_related("category", "brand"), pk=request.POST.get("product_id"))
        action = (request.POST.get("action") or "").strip()
        redirect_to = request.POST.get("next") or reverse("store:dashboard-products")

        if action == "publish_telegram":
            if not product.is_active or product.is_sold_out:
                messages.warning(request, f"{product.title} must be active and in stock before it can be posted to Telegram.")
            else:
                posted = post_product_to_channel(product, force=True)
                if posted:
                    messages.success(request, f"{product.title} was posted to Telegram.")
                else:
                    messages.warning(request, f"{product.title} could not be posted. Check Telegram and media configuration.")
        else:
            messages.error(request, "That product action is not supported.")
        return redirect(redirect_to)

    query = (request.GET.get("q") or "").strip()
    category_slug = (request.GET.get("category") or "").strip()
    state = (request.GET.get("state") or "").strip()

    products = Product.objects.select_related("category", "brand").order_by("-updated_at", "-created_at")
    if category_slug:
        products = products.filter(category__slug=category_slug)
    if state == "active":
        products = products.filter(is_active=True)
    elif state == "inactive":
        products = products.filter(is_active=False)
    elif state == "featured":
        products = products.filter(is_featured=True)
    elif state == "sold-out":
        products = products.filter(is_sold_out=True)
    elif state == "low-stock":
        products = products.filter(stock_quantity__lte=3)

    if query:
        products = products.filter(
            Q(title__icontains=query)
            | Q(sku__icontains=query)
            | Q(slug__icontains=query)
            | Q(category__title__icontains=query)
            | Q(brand__title__icontains=query)
        )

    summary = products.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(is_active=True)),
        featured=Count("id", filter=Q(is_featured=True)),
        sold_out=Count("id", filter=Q(is_sold_out=True)),
        low_stock=Count("id", filter=Q(stock_quantity__lte=3)),
    )

    paginator = Paginator(products, 16)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = _dashboard_context(
        request,
        section="products",
        title="Products",
        intro="Search, filter, and publish merchandise quickly, then open the full editor only when deeper merchandising work is needed.",
        products=page_obj,
        product_summary=summary,
        category_options=Category.objects.filter(is_active=True).order_by("title"),
        filters={"q": query, "category": category_slug, "state": state},
        query_string_without_page=_query_string_without(request, "page"),
    )
    return render(request, "dashboard/products.html", context)


@staff_required
def dashboard_product_edit(request, product_id=None):
    product = None
    if product_id is not None:
        product = get_object_or_404(
            Product.objects.select_related("category", "brand").prefetch_related("p_images", "size_inventory"),
            pk=product_id,
        )

    if request.method == "POST":
        form = DashboardProductForm(request.POST, request.FILES, instance=product)
        image_formset = decorate_dashboard_formset(
            ProductImageFormSet(request.POST, request.FILES, instance=product, prefix="images")
        )
        size_formset = decorate_dashboard_formset(
            ProductSizeStockFormSet(request.POST, instance=product, prefix="sizes")
        )

        if form.is_valid() and image_formset.is_valid() and size_formset.is_valid():
            with transaction.atomic():
                with suspend_telegram_autopublish():
                    saved_product = form.save()
                    image_formset.instance = saved_product
                    image_formset.save()
                    size_formset.instance = saved_product
                    size_formset.save()

            should_publish = "save_and_publish" in request.POST
            if should_publish and saved_product.is_active and not saved_product.is_sold_out:
                posted = post_product_to_channel(saved_product, force=True)
                if posted:
                    messages.success(request, f"{saved_product.title} was saved and posted to Telegram.")
                else:
                    messages.warning(
                        request,
                        f"{saved_product.title} was saved, but Telegram publishing did not complete.",
                    )
            elif should_publish:
                messages.warning(
                    request,
                    f"{saved_product.title} was saved, but it must be active and in stock before Telegram publishing.",
                )
            else:
                messages.success(request, f"{saved_product.title} was saved.")

            return redirect("store:dashboard-product-edit", product_id=saved_product.id)
    else:
        form = DashboardProductForm(instance=product)
        image_formset = decorate_dashboard_formset(ProductImageFormSet(instance=product, prefix="images"))
        size_formset = decorate_dashboard_formset(ProductSizeStockFormSet(instance=product, prefix="sizes"))

    context = _dashboard_context(
        request,
        section="products",
        title="Edit Product" if product else "New Product",
        intro="A merchandising-focused editor with gallery, inventory rows, and launch controls in one responsive workspace.",
        form=form,
        image_formset=image_formset,
        size_formset=size_formset,
        product=product,
        product_affiliate_pattern=_absolute_affiliate_pattern(product) if product else None,
        gallery_images=list(product.p_images.all()) if product else [],
    )
    return render(request, "dashboard/product_form.html", context)
