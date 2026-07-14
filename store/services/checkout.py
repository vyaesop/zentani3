"""Order placement domain logic: stock-locked order creation, affiliate
commissions, coupon usage, and cart clearing. Views orchestrate; this does
the work (and P1 task handlers reuse the pricing helpers)."""
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import models, transaction
from django.utils import timezone

from store.constants import AFFILIATE_RATE_PERCENT
from store.models import (
    AffiliateClick,
    AffiliateCommission,
    Cart,
    Coupon,
    Order,
    Product,
    ProductSizeStock,
)
from store.telegram_notify import suspend_telegram_autopublish


class OrderPlacementError(Exception):
    """Raised when the cart can no longer be fulfilled."""


def coupon_issue(coupon):
    """Return a human-readable problem with the coupon, or None if usable."""
    if not coupon:
        return "Coupon does not exist."

    today = timezone.localdate()

    if not coupon.active:
        return "This coupon is not active."
    if coupon.active_date and today < coupon.active_date:
        return "This coupon is not active yet."
    if coupon.expiry_date and today > coupon.expiry_date:
        return "This coupon has expired."
    if coupon.discount is None or coupon.discount <= 0 or coupon.discount > 100:
        return "This coupon is invalid."

    return None


def effective_unit_price(product_price, coupon):
    if coupon_issue(coupon):
        return product_price

    discount_percentage = Decimal(coupon.discount) / Decimal(100)
    discount_amount_per_item = product_price * discount_percentage
    return product_price - discount_amount_per_item


def calculate_commission_amount(line_total, rate=AFFILIATE_RATE_PERCENT):
    return (line_total * rate / Decimal("100")).quantize(Decimal("0.01"))


@dataclass
class OrderPlacement:
    order_count: int = 0
    order_total: Decimal = Decimal("0.00")
    order_ids: list = field(default_factory=list)
    order_lines: list = field(default_factory=list)


def place_order(user, cart_items, *, affiliate_profile=None, affiliate_click_id=None):
    """Atomically convert cart rows into orders with stock decrement.

    Locks each product (and size row) before checking stock, creates one Order
    per cart line, records affiliate commissions and coupon usage, clears the
    cart, and marks the referring click converted. Raises OrderPlacementError
    when any line can no longer be fulfilled (nothing is committed).
    """
    placement = OrderPlacement()

    with transaction.atomic():
        commissions_to_create = []
        # Stock decrements are not merchandising changes — don't let the
        # product post_save signal enqueue Telegram channel posts.
        with suspend_telegram_autopublish():
            for cart_item in cart_items:
                locked_product = Product.objects.select_for_update().get(id=cart_item.product_id)
                locked_size_stock = None
                if cart_item.size:
                    locked_size_stock = (
                        ProductSizeStock.objects.select_for_update()
                        .filter(product_id=cart_item.product_id, size=cart_item.size)
                        .first()
                    )

                available_quantity = locked_size_stock.quantity if locked_size_stock else locked_product.stock_quantity
                if locked_product.is_sold_out or available_quantity < cart_item.quantity:
                    raise OrderPlacementError(
                        f"{locked_product.title} ({cart_item.size or 'default size'}) no longer has enough stock to fulfill your order."
                    )

                effective_price_per_item = effective_unit_price(cart_item.product.price, cart_item.coupon)
                line_total_for_order = cart_item.quantity * effective_price_per_item
                order = Order.objects.create(
                    user=user,
                    product=locked_product,
                    quantity=cart_item.quantity,
                    size=cart_item.size,
                    price_at_purchase=effective_price_per_item,
                    line_total=line_total_for_order,
                )
                placement.order_count += 1
                placement.order_total += line_total_for_order
                placement.order_ids.append(order.id)
                placement.order_lines.append(
                    {
                        "title": cart_item.product.title,
                        "sku": cart_item.product.sku,
                        "quantity": cart_item.quantity,
                        "size": cart_item.size or "N/A",
                        "unit_price": f"{effective_price_per_item:.2f}",
                        "line_total": f"{line_total_for_order:.2f}",
                        "coupon": cart_item.coupon.code if cart_item.coupon else "N/A",
                        "status": order.status,
                    }
                )

                if affiliate_profile:
                    commission_amount = calculate_commission_amount(line_total_for_order)
                    if commission_amount > Decimal("0.00"):
                        commissions_to_create.append(
                            AffiliateCommission(
                                affiliate=affiliate_profile,
                                order=order,
                                customer=user,
                                rate=AFFILIATE_RATE_PERCENT,
                                amount=commission_amount,
                            )
                        )

                if locked_size_stock:
                    locked_size_stock.quantity = max(0, locked_size_stock.quantity - cart_item.quantity)
                    locked_size_stock.save(update_fields=["quantity", "updated_at"])

                locked_product.stock_quantity = max(0, locked_product.stock_quantity - cart_item.quantity)
                if locked_product.stock_quantity == 0:
                    locked_product.is_sold_out = True
                    locked_product.save(update_fields=["stock_quantity", "is_sold_out", "updated_at"])
                else:
                    locked_product.save(update_fields=["stock_quantity", "updated_at"])

        if commissions_to_create:
            AffiliateCommission.objects.bulk_create(commissions_to_create)

        # Record coupon usage atomically for each unique coupon applied.
        used_coupon_ids = {cart_item.coupon_id for cart_item in cart_items if cart_item.coupon_id}
        for coupon_id in used_coupon_ids:
            Coupon.objects.filter(pk=coupon_id).update(used_count=models.F("used_count") + 1)

        Cart.objects.filter(id__in=[cart_item.id for cart_item in cart_items]).delete()

        if affiliate_click_id:
            AffiliateClick.objects.filter(id=affiliate_click_id).update(converted=True)

    return placement
