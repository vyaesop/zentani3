"""Colour variants: one garment, several colours, one product per colour.

Design (the "sibling link" model):

* Every colour is a full ``Product`` with its own page, SKU, photos, price,
  stock and Telegram post. Nothing about a single-colour product changes.
* ``ProductColorGroup`` only says "these products are colours of the same
  garment". The storefront uses it to draw swatches that link between the
  colour pages; the merchant feed uses it as ``item_group_id``.
* Groups are invisible plumbing for staff: they are created when the first
  sibling is added and dissolved when a group drops to one member.

Everything that mutates products here runs under
``suspend_telegram_autopublish`` so creating or syncing colours never posts
to the channel by accident — publishing stays an explicit "Save & post".
"""
import re

from django.db import transaction
from django.utils.text import slugify

from store.cache_utils import bump_catalog_version
from store.models import Product, ProductColorGroup, ProductImages
from store.services.inventory import set_product_sizes
from store.telegram_notify import suspend_telegram_autopublish


# Copy-once fields: they describe the garment, not the colour, so a new colour
# starts with the same values. Staff can still edit them per colour afterwards.
COPIED_FIELDS = (
    "short_description",
    "detail_description",
    "material",
    "fit_notes",
    "care_notes",
    "measurements",
    "delivery_note",
    "return_note",
    "seo_description",
    "category",
    "brand",
    "compare_at_price",
    "is_featured",
)

# Fields "Copy details to other colours" pushes from one colour to the rest.
# Deliberately excludes everything colour-specific: title, slug, SKU, colour,
# photos, alt text, SEO title, stock and visibility. Price is opt-in.
SHARED_DETAIL_FIELDS = (
    "short_description",
    "detail_description",
    "material",
    "fit_notes",
    "care_notes",
    "measurements",
    "delivery_note",
    "return_note",
    "category",
    "brand",
)

SHARED_DETAIL_LABELS = {
    "short_description": "short description",
    "detail_description": "detail description",
    "material": "material",
    "fit_notes": "fit notes",
    "care_notes": "care notes",
    "measurements": "measurements",
    "delivery_note": "delivery note",
    "return_note": "return note",
    "category": "collection",
    "brand": "brand",
    "price": "price",
}


def unique_product_slug(base, *, exclude_pk=None):
    """Return ``base`` (slugified, trimmed) or the first free ``base-N``.

    Product.slug is not unique at the database level, but the detail URL
    looks products up by slug, so duplicates would break pages.
    """
    slug = slugify(base or "")[:150] or "product"
    candidate = slug
    suffix = 2
    while Product.objects.filter(slug=candidate).exclude(pk=exclude_pk).exists():
        candidate = f"{slug}-{suffix}"
        suffix += 1
    return candidate


def unique_product_sku(base, *, exclude_pk=None):
    base = (base or "").strip()[:240] or "SKU"
    candidate = base
    suffix = 2
    while Product.objects.filter(sku=candidate).exclude(pk=exclude_pk).exists():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def variant_sku_base(source):
    """The source SKU without its own colour token, so clones never stack
    tokens (SKU-BLUE-RED). Shared with the form's live SKU suggestion."""
    base_sku = (source.sku or "").strip()
    if source.color:
        source_token = slugify(source.color).upper().replace("-", "")[:24]
        if source_token and base_sku.upper().endswith(f"-{source_token}"):
            base_sku = base_sku[: -(len(source_token) + 1)]
    return base_sku


def suggest_variant_sku(source, color):
    """``<source SKU>-<COLOUR>``, made unique — staff can still overwrite it."""
    color_token = slugify(color or "").upper().replace("-", "")[:24] or "ALT"
    base_sku = variant_sku_base(source)
    return unique_product_sku(f"{base_sku}-{color_token}" if base_sku else color_token)


def suggest_variant_title(source, color):
    """Swap the old colour word for the new one when the title carries it.

    "Black Linen Shirt" + "Blue" -> "Blue Linen Shirt". A title without the
    colour word is kept as-is; the colour lives in the swatch and facts.
    """
    title = (source.title or "").strip()
    old = (source.color or "").strip()
    new = (color or "").strip()
    if old and new and old.casefold() != new.casefold():
        pattern = re.compile(rf"\b{re.escape(old)}\b", re.IGNORECASE)
        swapped, count = pattern.subn(new, title, count=1)
        if count:
            return swapped[:150]
    return title[:150]


def suggest_variant_alt_text(source, color, title):
    alt = (source.image_alt_text or "").strip()
    old = (source.color or "").strip()
    if alt and old and color and old.casefold() != color.casefold():
        swapped, count = re.compile(rf"\b{re.escape(old)}\b", re.IGNORECASE).subn(color, alt, count=1)
        if count:
            return swapped[:180]
    if color:
        return f"{title} in {color}"[:180]
    return (alt or title)[:180]


def ensure_color_group(product):
    """Return the product's group, creating one named after the product."""
    if product.color_group_id:
        return product.color_group
    group = ProductColorGroup.objects.create(name=(product.title or product.sku)[:150])
    Product.objects.filter(pk=product.pk).update(color_group=group)
    product.color_group = group
    return group


def create_color_variant(
    source,
    *,
    color,
    cover_image,
    gallery_images=(),
    sku=None,
    title=None,
    price=None,
    compare_at_price=None,
    sizes=None,
    is_active=False,
):
    """Clone ``source`` as a new colour and put both in the same group.

    Only the colour-specific inputs are required (colour name and a cover
    photo). Everything descriptive is copied from the source; sizes default
    to the source's size list and start at the configured default stock.
    The new product is hidden unless ``is_active`` is passed so nothing
    reaches shoppers or Telegram before staff have reviewed it.
    """
    color = (color or "").strip()[:80]
    if not color:
        raise ValueError("A colour name is required.")
    if not cover_image:
        raise ValueError("A cover photo is required.")

    title = (title or "").strip()[:150]
    if not title or title.casefold() == (source.title or "").strip().casefold():
        # Untouched (or blank) title: swap the colour word for the new colour,
        # as the "Add a colour" form promises.
        title = suggest_variant_title(source, color)
    sku = (sku or "").strip()[:255] or suggest_variant_sku(source, color)
    if Product.objects.filter(sku=sku).exists():
        raise ValueError(f'SKU "{sku}" is already used by another product.')
    if sizes is None:
        sizes = [row.size for row in source.size_inventory.all()]

    with transaction.atomic():
        with suspend_telegram_autopublish():
            group = ensure_color_group(source)
            variant = Product(
                title=title,
                slug=unique_product_slug(f"{title} {color}" if color.casefold() not in title.casefold() else title),
                sku=sku,
                color=color,
                color_group=group,
                price=source.price if price is None else price,
                seo_title="",
                image_alt_text=suggest_variant_alt_text(source, color, title),
                is_active=bool(is_active),
                is_sold_out=False,
                stock_quantity=0,
            )
            for field_name in COPIED_FIELDS:
                setattr(variant, field_name, getattr(source, field_name))
            if compare_at_price is not None or price is not None:
                # A price given explicitly means the old markdown no longer applies
                # unless the caller also passed a compare-at price.
                variant.compare_at_price = compare_at_price
            variant.product_image = cover_image
            variant.save()

            for uploaded in gallery_images or ():
                if not uploaded:
                    continue
                content_type = getattr(uploaded, "content_type", "") or ""
                if content_type and not content_type.startswith("image/"):
                    continue
                ProductImages.objects.create(product=variant, image=uploaded)

            if sizes:
                set_product_sizes(variant, sizes)
    return variant


def link_products(source, other):
    """Make ``other`` a colour of ``source``'s garment.

    If ``other`` already belongs to a different group the two groups merge,
    so a merchandiser can join two partially-linked families in one step.
    """
    if other.pk == source.pk:
        return source.color_group
    with transaction.atomic():
        group = ensure_color_group(source)
        if other.color_group_id and other.color_group_id != group.pk:
            old_group_id = other.color_group_id
            Product.objects.filter(color_group_id=old_group_id).update(color_group=group)
            ProductColorGroup.objects.filter(pk=old_group_id).delete()
        else:
            Product.objects.filter(pk=other.pk).update(color_group=group)
        other.color_group = group
    bump_catalog_version()
    return group


def unlink_product(product):
    """Take a product out of its colour group; dissolve groups left with one member."""
    group_id = product.color_group_id
    if not group_id:
        return
    with transaction.atomic():
        Product.objects.filter(pk=product.pk).update(color_group=None)
        product.color_group = None
        remaining = list(Product.objects.filter(color_group_id=group_id).values_list("pk", flat=True))
        if len(remaining) <= 1:
            Product.objects.filter(color_group_id=group_id).update(color_group=None)
            ProductColorGroup.objects.filter(pk=group_id).delete()
    bump_catalog_version()


def sync_shared_details(source, *, include_price=False):
    """Push the garment-level fields from ``source`` to its other colours.

    Returns the number of sibling products updated. Runs with Telegram
    auto-publish suspended: a description tweak must not re-post every colour.
    """
    siblings = list(source.color_siblings(include_hidden=True))
    if not siblings:
        return 0
    fields = list(SHARED_DETAIL_FIELDS) + (["price", "compare_at_price"] if include_price else [])
    with transaction.atomic():
        with suspend_telegram_autopublish():
            for sibling in siblings:
                for field_name in fields:
                    setattr(sibling, field_name, getattr(source, field_name))
                sibling.save(update_fields=[*fields, "updated_at"])
    return len(siblings)


def color_family(product, *, include_hidden=False):
    """The product plus its siblings, swatch-ordered, with the current one flagged.

    Returns [] when the product has no other visible colours so templates can
    hide the swatch row with a single ``{% if %}``. No query for ungrouped
    products.
    """
    if not product.color_group_id:
        return []
    siblings = list(product.color_siblings(include_hidden=include_hidden))
    if not siblings:
        return []
    members = sorted([product, *siblings], key=lambda item: (item.created_at or 0, item.pk))
    return [
        {
            "product": member,
            "is_current": member.pk == product.pk,
            "label": member.color_label,
        }
        for member in members
    ]


def color_count_map(products):
    """{color_group_id: number of live colours} for a page of products, in one query.

    Lets product cards say "3 colours" without an N+1. Products outside any
    group cost nothing; when no product on the page is grouped no query runs.
    """
    from django.db.models import Count

    group_ids = {getattr(item, "color_group_id", None) for item in products}
    group_ids.discard(None)
    if not group_ids:
        return {}
    rows = (
        Product.objects.filter(is_active=True, color_group_id__in=group_ids)
        .order_by()  # drop Meta.ordering so it can't leak into GROUP BY
        .values("color_group_id")
        .annotate(n=Count("id"))
    )
    return {row["color_group_id"]: row["n"] for row in rows if row["n"] > 1}


def colour_name_suggestions(limit=24):
    """Colours already used in the catalogue, most recent first — datalist fodder."""
    names = []
    seen = set()
    for value in Product.objects.exclude(color="").order_by("-updated_at").values_list("color", flat=True)[:200]:
        cleaned = (value or "").strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            names.append(cleaned)
        if len(names) >= limit:
            break
    return names
