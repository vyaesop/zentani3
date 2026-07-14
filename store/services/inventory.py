"""Size inventory management.

ProductSizeStock rows are the single source of truth for sizes. Callers that
mutate a product's size list (dashboard form, admin scripts) go through
set_product_sizes(); Product.save() itself has no inventory side effects.
"""
import re

from django.db import models

from store.models import Product, ProductSizeStock


def parse_size_list(value):
    """Normalize free text (commas/newlines) into a deduped list of sizes."""
    normalized_sizes = []
    seen = set()
    for chunk in re.split(r"[\n,]+", value or ""):
        size = " ".join(chunk.split()).strip()
        if not size:
            continue
        lookup = size.casefold()
        if lookup in seen:
            continue
        seen.add(lookup)
        normalized_sizes.append(size)
    return normalized_sizes


def set_product_sizes(product, sizes, default_stock=Product.DEFAULT_STOCK_PER_SIZE):
    """Reconcile ProductSizeStock rows against the desired size list.

    Creates missing sizes at default_stock, keeps quantities of existing ones,
    deletes removed ones, then updates the product's aggregate stock/sold-out
    columns (without triggering Product.save side effects).
    """
    if not product.pk:
        raise ValueError("Product must be saved before assigning sizes.")

    desired_sizes = list(sizes)
    desired_keys = {size.casefold() for size in desired_sizes}
    existing_inventory = {
        item.size.casefold(): item
        for item in ProductSizeStock.objects.filter(product=product)
        if item.size and item.size.strip()
    }

    for lookup_key, inventory_row in existing_inventory.items():
        if lookup_key not in desired_keys:
            inventory_row.delete()

    kept_quantities = []
    for size in desired_sizes:
        inventory_row = existing_inventory.get(size.casefold())
        if inventory_row:
            if inventory_row.size != size:
                inventory_row.size = size
                inventory_row.save(update_fields=["size", "updated_at"])
            kept_quantities.append(inventory_row.quantity)
            continue
        inventory_row = ProductSizeStock.objects.create(
            product=product,
            size=size,
            quantity=default_stock,
        )
        kept_quantities.append(inventory_row.quantity)

    if desired_sizes:
        total_quantity = sum(kept_quantities)
        sold_out = total_quantity <= 0
        if product.stock_quantity != total_quantity or product.is_sold_out != sold_out:
            product.stock_quantity = total_quantity
            product.is_sold_out = sold_out
            Product.objects.filter(pk=product.pk).update(
                stock_quantity=total_quantity,
                is_sold_out=sold_out,
            )
    elif product.stock_quantity < 0:
        product.stock_quantity = 0
        Product.objects.filter(pk=product.pk).update(stock_quantity=0)

    return desired_sizes


def reconcile_sold_out(product):
    """Recompute and persist is_sold_out from actual stock."""
    if ProductSizeStock.objects.filter(product_id=product.pk).exists():
        total = (
            ProductSizeStock.objects.filter(product_id=product.pk)
            .aggregate(total=models.Sum("quantity"))["total"]
            or 0
        )
        sold_out = total <= 0
    else:
        sold_out = product.stock_quantity <= 0

    if product.is_sold_out != sold_out:
        product.is_sold_out = sold_out
        Product.objects.filter(pk=product.pk).update(is_sold_out=sold_out)
    return sold_out
