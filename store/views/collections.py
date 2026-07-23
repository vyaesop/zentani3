"""Collection browsing: filtered/sorted product grids, search, directories."""
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Case, F, IntegerField, Max, Min, Q, Value, When
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from store.cache_utils import COLLECTION_META_TTL, collection_meta_key
from store.constants import (
    COLLECTION_PAGE_SIZE,
    COLLECTION_SORT_OPTIONS,
    DIRECTORY_PAGE_SIZE,
)
from store.models import Brand, Category, Product, ProductSizeStock

from .catalog import (
    PRODUCT_LIST_FIELDS,
    _recently_viewed_products,
    _saved_product_ids_for_user,
    _size_sort_key,
)
from .common import (
    _normalized_multi_param,
    _parse_decimal_param,
    _querydict_pairs,
    _querystring_without,
    _url_with_query,
)


def _search_discovery_context(request):
    return {
        "search_help_categories": Category.objects.filter(is_active=True).only("id", "title", "slug").order_by("title")[:6],
        "search_help_brands": Brand.objects.filter(is_active=True).only("id", "title", "slug").order_by("title")[:6],
        "recently_viewed_products": _recently_viewed_products(request, limit=4),
    }




def _collection_sort_choices(current_sort, include_relevance=False):
    options = list(COLLECTION_SORT_OPTIONS)
    if include_relevance:
        options = [("relevance", "Most relevant", "relevance"), *options]

    return [
        {
            "value": value,
            "label": label,
            "selected": value == current_sort,
        }
        for value, label, _ in options
    ]


def _browse_text_query(current_query):
    if not current_query:
        return Q()

    return (
        Q(title__icontains=current_query)
        | Q(short_description__icontains=current_query)
        | Q(detail_description__icontains=current_query)
        | Q(category__title__icontains=current_query)
        | Q(brand__title__icontains=current_query)
        | Q(sku__icontains=current_query)
        | Q(material__icontains=current_query)
        | Q(color__icontains=current_query)
    )


def _search_rank_expression(current_query):
    if not current_query:
        return Value(0, output_field=IntegerField())

    return Case(
        When(title__iexact=current_query, then=Value(90)),
        When(title__istartswith=current_query, then=Value(75)),
        When(brand__title__iexact=current_query, then=Value(65)),
        When(category__title__iexact=current_query, then=Value(60)),
        When(title__icontains=current_query, then=Value(50)),
        When(short_description__icontains=current_query, then=Value(35)),
        When(detail_description__icontains=current_query, then=Value(25)),
        When(material__icontains=current_query, then=Value(18)),
        When(color__icontains=current_query, then=Value(15)),
        default=Value(0),
        output_field=IntegerField(),
    )


def _collection_size_options(queryset):
    sizes = set()
    for size_value in ProductSizeStock.objects.filter(product__in=queryset).values_list("size", flat=True):
        normalized = (size_value or "").strip()
        if normalized:
            sizes.add(normalized)
    return sorted(sizes, key=_size_sort_key)


def _build_collection_state(
    request,
    base_queryset,
    *,
    form_action=None,
    show_category_filters=True,
    show_brand_filters=True,
    include_relevance_sort=False,
):
    current_query = (request.GET.get("q") or "").strip()
    selected_categories = (
        _normalized_multi_param(request.GET.getlist("category")) if show_category_filters else []
    )
    selected_brands = (
        _normalized_multi_param(request.GET.getlist("brand")) if show_brand_filters else []
    )
    selected_sizes = _normalized_multi_param(request.GET.getlist("size"))
    availability = "in-stock" if request.GET.get("availability") == "in-stock" else ""
    default_sort = "relevance" if include_relevance_sort and current_query else "newest"
    current_sort = (request.GET.get("sort") or default_sort).strip()
    sort_mapping = {value: ordering for value, _, ordering in COLLECTION_SORT_OPTIONS}
    if include_relevance_sort:
        sort_mapping["relevance"] = "relevance"
    sort_ordering = sort_mapping.get(current_sort, sort_mapping[default_sort])
    if current_sort not in sort_mapping:
        current_sort = default_sort

    query_scoped_queryset = base_queryset
    if current_query:
        query_scoped_queryset = query_scoped_queryset.filter(_browse_text_query(current_query))

    # Price bounds and the size-option scan only depend on the scope (path +
    # text query), not on filters/sort/page — cache them per catalog version.
    meta_cache_key = collection_meta_key(form_action or request.path, current_query)
    collection_meta = cache.get(meta_cache_key)
    if collection_meta is None:
        price_bounds = query_scoped_queryset.aggregate(min_price=Min("price"), max_price=Max("price"))
        collection_meta = {
            "min_price": price_bounds.get("min_price"),
            "max_price": price_bounds.get("max_price"),
            "size_options": _collection_size_options(query_scoped_queryset),
        }
        cache.set(meta_cache_key, collection_meta, COLLECTION_META_TTL)
    min_price_bound = collection_meta["min_price"]
    max_price_bound = collection_meta["max_price"]
    current_min_price = _parse_decimal_param(request.GET.get("min_price"))
    current_max_price = _parse_decimal_param(request.GET.get("max_price"))

    filtered_queryset = query_scoped_queryset
    if selected_categories:
        filtered_queryset = filtered_queryset.filter(category__slug__in=selected_categories)
    if selected_brands:
        filtered_queryset = filtered_queryset.filter(brand__slug__in=selected_brands)
    if selected_sizes:
        size_query = Q()
        for size in selected_sizes:
            size_query |= Q(size_inventory__size__iexact=size, size_inventory__quantity__gt=0)
        filtered_queryset = filtered_queryset.filter(size_query)
    if availability:
        filtered_queryset = filtered_queryset.filter(is_sold_out=False)
    if current_min_price is not None:
        filtered_queryset = filtered_queryset.filter(price__gte=current_min_price)
    if current_max_price is not None:
        filtered_queryset = filtered_queryset.filter(price__lte=current_max_price)

    filtered_queryset = filtered_queryset.distinct()
    if sort_ordering == "relevance":
        filtered_queryset = filtered_queryset.annotate(search_rank=_search_rank_expression(current_query)).order_by("-search_rank", "-created_at", "-id")
    else:
        filtered_queryset = filtered_queryset.order_by(sort_ordering, "-id")

    paginator = Paginator(filtered_queryset, COLLECTION_PAGE_SIZE)
    paged_products = paginator.get_page(request.GET.get("page"))
    page_numbers = paginator.get_elided_page_range(
        number=paged_products.number,
        on_each_side=1,
        on_ends=1,
    )

    result_summary = (
        f"Showing {paged_products.start_index()}-{paged_products.end_index()} of {paginator.count}"
        if paginator.count
        else "No products match this view yet"
    )

    category_label_map = dict(
        Category.objects.filter(slug__in=selected_categories).values_list("slug", "title")
    )
    brand_label_map = dict(
        Brand.objects.filter(slug__in=selected_brands).values_list("slug", "title")
    )

    active_filters = []
    if selected_categories:
        active_filters.extend(
            [f"Collection: {category_label_map.get(value, value)}" for value in selected_categories]
        )
    if selected_brands:
        active_filters.extend(
            [f"Brand: {brand_label_map.get(value, value)}" for value in selected_brands]
        )
    if selected_sizes:
        active_filters.extend([f"Size: {value}" for value in selected_sizes])
    if availability:
        active_filters.append("In stock only")
    if current_min_price is not None:
        active_filters.append(f"Min {current_min_price:.2f} ETB")
    if current_max_price is not None:
        active_filters.append(f"Max {current_max_price:.2f} ETB")
    if current_sort not in ("newest", default_sort):
        sort_labels = {value: label for value, label, _ in COLLECTION_SORT_OPTIONS}
        sort_labels["relevance"] = "Most relevant"
        selected_sort_label = sort_labels.get(current_sort)
        if selected_sort_label:
            active_filters.append(f"Sort: {selected_sort_label}")

    reset_params = request.GET.copy()
    for key in ("category", "brand", "size", "availability", "min_price", "max_price", "sort", "page"):
        reset_params.pop(key, None)

    sort_hidden_params = request.GET.copy()
    sort_hidden_params.pop("sort", None)
    sort_hidden_params.pop("page", None)

    return {
        "products": paged_products,
        "page_obj": paged_products,
        "product_count": paginator.count,
        "page_numbers": page_numbers,
        "saved_product_ids": _saved_product_ids_for_user(request.user),
        "browse_state": {
            "form_action": form_action or request.path,
            "sort_options": _collection_sort_choices(current_sort, include_relevance=include_relevance_sort and bool(current_query)),
            "sort_hidden_fields": _querydict_pairs(sort_hidden_params),
            "page_query": _querystring_without(request, "page"),
            "current_query": current_query,
            "current_min_price": f"{current_min_price:.2f}" if current_min_price is not None else "",
            "current_max_price": f"{current_max_price:.2f}" if current_max_price is not None else "",
            "min_price_bound": f"{min_price_bound:.2f}" if min_price_bound is not None else "",
            "max_price_bound": f"{max_price_bound:.2f}" if max_price_bound is not None else "",
            "show_category_filters": show_category_filters,
            "show_brand_filters": show_brand_filters,
            "selected_categories": selected_categories,
            "selected_brands": selected_brands,
            "selected_sizes": selected_sizes,
            "availability": availability,
            "size_options": collection_meta["size_options"],
            "result_summary": result_summary,
            "active_filters": active_filters,
            "reset_filters_url": _url_with_query(form_action or request.path, reset_params),
        },
    }


def _render_collection(request, template_name, context):
    """Full page normally; just the next page of cards for load-more requests."""
    if request.GET.get("fragment") == "items":
        return render(request, "store/_collection_grid_items.html", context)
    return render(request, template_name, context)


def search_view(request):
    base_products = Product.objects.filter(is_active=True).select_related("category", "brand").prefetch_related("size_inventory").only(*PRODUCT_LIST_FIELDS)
    context = _build_collection_state(
        request,
        base_products,
        form_action=reverse("store:search"),
        include_relevance_sort=True,
    )
    context["query"] = context["browse_state"]["current_query"]
    context.update(_search_discovery_context(request))
    return _render_collection(request, "store/search.html", context)


def search_suggestions(request):
    query = (request.GET.get("q") or "").strip()
    if len(query) < 2:
        return HttpResponse("")

    product_suggestions = list(
        Product.objects.filter(is_active=True)
        .filter(_browse_text_query(query))
        .annotate(search_rank=_search_rank_expression(query))
        .order_by("-search_rank", "-created_at")
        .values("title", "slug")[:5]
    )
    category_suggestions = list(
        Category.objects.filter(is_active=True, title__icontains=query).values("title", "slug")[:4]
    )
    brand_suggestions = list(
        Brand.objects.filter(is_active=True, title__icontains=query).values("title", "slug")[:4]
    )
    return render(
        request,
        "store/_search_suggestions.html",
        {
            "products": product_suggestions,
            "categories": category_suggestions,
            "brands": brand_suggestions,
        },
    )


def products(request):
    base_products = Product.objects.filter(is_active=True).select_related("category", "brand").prefetch_related("size_inventory").only(*PRODUCT_LIST_FIELDS)
    context = _build_collection_state(
        request,
        base_products,
        form_action=reverse("store:all-products"),
    )
    return _render_collection(request, "store/products.html", context)


def sale_products(request):
    base_products = (
        Product.objects.filter(is_active=True, compare_at_price__gt=F("price"))
        .select_related("category", "brand")
        .prefetch_related("size_inventory")
        .only(*PRODUCT_LIST_FIELDS)
    )
    context = _build_collection_state(
        request,
        base_products,
        form_action=reverse("store:sale-products"),
    )
    return _render_collection(request, "store/sale_products.html", context)


def all_categories(request):
    categories = Category.objects.filter(is_active=True).only("id", "title", "slug", "category_image")
    paginator = Paginator(categories, DIRECTORY_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "store/categories.html",
        {
            "categories": page_obj,
            "page_obj": page_obj,
            "page_numbers": paginator.get_elided_page_range(number=page_obj.number, on_each_side=1, on_ends=1),
            "page_query": _querystring_without(request, "page"),
            "directory_count": paginator.count,
        },
    )


def all_brands(request):
    brands = Brand.objects.filter(is_active=True).only("id", "title", "slug", "brand_image")
    paginator = Paginator(brands, DIRECTORY_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "store/brands.html",
        {
            "brands": page_obj,
            "page_obj": page_obj,
            "page_numbers": paginator.get_elided_page_range(number=page_obj.number, on_each_side=1, on_ends=1),
            "page_query": _querystring_without(request, "page"),
            "directory_count": paginator.count,
        },
    )


def category_products(request, slug):
    category = get_object_or_404(Category, slug=slug)
    base_products = Product.objects.filter(is_active=True, category=category).select_related("category", "brand").prefetch_related("size_inventory").only(*PRODUCT_LIST_FIELDS)
    context = _build_collection_state(
        request,
        base_products,
        form_action=reverse("store:category-products", kwargs={"slug": category.slug}),
        show_category_filters=False,
    )
    context["category"] = category
    return _render_collection(request, "store/category_products.html", context)


def brand_products(request, slug):
    brand = get_object_or_404(Brand, slug=slug)
    base_products = Product.objects.filter(is_active=True, brand=brand).select_related("category", "brand").prefetch_related("size_inventory").only(*PRODUCT_LIST_FIELDS)
    context = _build_collection_state(
        request,
        base_products,
        form_action=reverse("store:brand-products", kwargs={"slug": brand.slug}),
        show_brand_filters=False,
    )
    context["brand"] = brand
    return _render_collection(request, "store/brand_products.html", context)
