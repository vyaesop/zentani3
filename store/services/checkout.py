"""Order placement domain logic: stock-locked order creation, order-group
header (number, contact snapshot, delivery fee, totals, payment state),
affiliate commissions, coupon usage, cart clearing, and cancellation with
stock restoration. Views orchestrate; this does the work (and task handlers
reuse the pricing helpers)."""
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import models, transaction
from django.utils import timezone

from store.constants import (
    ADDIS_FREE_SHIPPING_THRESHOLD,
    ADDIS_SHIPPING_FEE,
    AFFILIATE_RATE_PERCENT,
    OUTSIDE_ADDIS_SHIPPING_FEE,
)
from store.models import (
    AffiliateClick,
    AffiliateCommission,
    Cart,
    Coupon,
    Order,
    OrderGroup,
    Product,
    ProductEvent,
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
    if getattr(coupon, "is_exhausted", False):
        return "This coupon has been fully redeemed."

    return None


def effective_unit_price(product_price, coupon):
    if coupon_issue(coupon):
        return product_price

    discount_percentage = Decimal(coupon.discount) / Decimal(100)
    discount_amount_per_item = product_price * discount_percentage
    return product_price - discount_amount_per_item


def calculate_commission_amount(line_total, rate=AFFILIATE_RATE_PERCENT):
    return (line_total * rate / Decimal("100")).quantize(Decimal("0.01"))


# ── Delivery fees ────────────────────────────────────────────────────────────

def normalized_city(value):
    return (value or "").strip().lower()


def is_addis(city):
    return "addis" in normalized_city(city)


def delivery_fee_for(city, subtotal):
    """Flat fees: Addis (free above the threshold) or outside Addis.

    An unknown city yields 0 so the cart can show 'calculated at checkout'
    instead of guessing; the checkout itself always has a city.
    """
    if not normalized_city(city):
        return Decimal("0.00")
    if is_addis(city):
        if subtotal >= ADDIS_FREE_SHIPPING_THRESHOLD:
            return Decimal("0.00")
        return ADDIS_SHIPPING_FEE
    return OUTSIDE_ADDIS_SHIPPING_FEE


def delivery_note_for(city, subtotal):
    if not normalized_city(city):
        return f"Shipping is calculated once the delivery city is known. Addis starts at {ADDIS_SHIPPING_FEE:.0f} ETB."
    if is_addis(city):
        if subtotal >= ADDIS_FREE_SHIPPING_THRESHOLD:
            return "Addis delivery is free for this order total."
        shortfall = (ADDIS_FREE_SHIPPING_THRESHOLD - subtotal).quantize(Decimal("0.01"))
        return f"Addis delivery is {ADDIS_SHIPPING_FEE:.0f} ETB. Add {shortfall:,.0f} ETB more for free delivery."
    return f"Outside Addis delivery is {OUTSIDE_ADDIS_SHIPPING_FEE:.0f} ETB."


# ── Placement ────────────────────────────────────────────────────────────────

@dataclass
class OrderPlacement:
    order_count: int = 0
    order_total: Decimal = Decimal("0.00")  # subtotal of lines (pre-delivery)
    delivery_fee: Decimal = Decimal("0.00")
    grand_total: Decimal = Decimal("0.00")
    order_ids: list = field(default_factory=list)
    order_lines: list = field(default_factory=list)
    group: OrderGroup = None

    @property
    def number(self):
        return self.group.number if self.group else ""


def _contact_snapshot(user, guest_contact, address, contact_email=""):
    """Freeze who/where at checkout time so later address edits never rewrite history."""
    if user is None:
        snapshot = dict(guest_contact or {})
    else:
        snapshot = {
            "full_name": user.get_full_name() or user.username,
            "phone": getattr(address, "phone", "") or user.username,
            "city": getattr(address, "city", "") or "",
            "address": getattr(address, "address", "") or "",
            "email": user.email or "",
        }
    if contact_email and not snapshot.get("email"):
        snapshot["email"] = contact_email
    return {key: (value or "") for key, value in snapshot.items()}


def place_order(
    user,
    cart_items,
    *,
    guest_contact=None,
    session_key="",
    affiliate_profile=None,
    affiliate_click_id=None,
    address=None,
    payment_method=OrderGroup.PAYMENT_COD,
    contact_email="",
):
    """Atomically convert cart rows into an order group + lines with stock decrement.

    `user` is None for guest checkout — the contact snapshot then comes from
    `guest_contact` (full_name/phone/city/address[/email]); for signed-in
    customers it is taken from `address` (their chosen delivery address).

    Locks each product (and size row) before checking stock, creates one Order
    per cart line under a single OrderGroup, records affiliate commissions and
    coupon usage, clears the cart, and marks the referring click converted.
    Raises OrderPlacementError when any line can no longer be fulfilled
    (nothing is committed).
    """
    placement = OrderPlacement()
    contact = _contact_snapshot(user, guest_contact, address, contact_email=contact_email)
    delivery_city = contact.get("city", "")

    with transaction.atomic():
        group = OrderGroup.objects.create(
            number=OrderGroup.generate_number(),
            user=user,
            session_key=session_key if user is None else "",
            contact=contact,
            payment_method=payment_method,
            payment_status=(
                OrderGroup.PAYMENT_PENDING if payment_method == OrderGroup.PAYMENT_CHAPA else OrderGroup.PAYMENT_UNPAID
            ),
        )
        placement.group = group

        commissions_to_create = []
        coupon_codes = []
        # Stock decrements are not merchandising changes — don't let the
        # product post_save signal enqueue Telegram channel posts.
        with suspend_telegram_autopublish():
            for cart_item in cart_items:
                locked_product = Product.objects.select_for_update().get(id=cart_item.product_id)
                locked_size_stock = None
                if cart_item.size:
                    locked_size_stock = (
                        ProductSizeStock.objects
                        .select_for_update()
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
                    group=group,
                    session_key=session_key if user is None else "",
                    guest_contact=guest_contact if user is None else None,
                    product=locked_product,
                    quantity=cart_item.quantity,
                    size=cart_item.size,
                    price_at_purchase=effective_price_per_item,
                    line_total=line_total_for_order,
                )
                placement.order_count += 1
                placement.order_total += line_total_for_order
                placement.order_ids.append(order.id)
                if cart_item.coupon_id and cart_item.coupon.code not in coupon_codes:
                    coupon_codes.append(cart_item.coupon.code)
                ProductEvent.log(
                    ProductEvent.EVENT_PURCHASE,
                    locked_product,
                    user=user,
                    session_key=session_key if user is None else "",
                )
                placement.order_lines.append(
                    {
                        "order_id": order.id,
                        "product_id": locked_product.id,
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

        placement.delivery_fee = delivery_fee_for(delivery_city, placement.order_total)
        placement.grand_total = placement.order_total + placement.delivery_fee
        group.subtotal = placement.order_total
        group.delivery_fee = placement.delivery_fee
        group.total = placement.grand_total
        group.coupon_code = ", ".join(coupon_codes)[:30]
        group.save(update_fields=["subtotal", "delivery_fee", "total", "coupon_code", "updated_at"])

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


# ── Cancellation ─────────────────────────────────────────────────────────────

def cancel_order_line(order, *, restore_stock=True):
    """Mark one line Cancelled and return its units to inventory (once).

    Safe to call repeatedly: stock is only restored the first time a line moves
    to Cancelled. Returns True when the status actually changed.
    """
    from store.services.inventory import restore_stock as _restore_stock

    with transaction.atomic():
        locked = Order.objects.select_for_update().select_related("product").get(pk=order.pk)
        changed = locked.status != "Cancelled"
        update_fields = []
        if changed:
            locked.status = "Cancelled"
            update_fields.append("status")
        if restore_stock and not locked.stock_restored:
            _restore_stock(locked.product, locked.size, locked.quantity)
            locked.stock_restored = True
            update_fields.append("stock_restored")
        if update_fields:
            locked.save(update_fields=update_fields)
        order.status = locked.status
        order.stock_restored = locked.stock_restored
    return changed


def mark_group_paid(group, *, reference=""):
    """Record a successful online payment (idempotent)."""
    if group.payment_status == OrderGroup.PAYMENT_PAID:
        return False
    group.payment_status = OrderGroup.PAYMENT_PAID
    group.paid_at = timezone.now()
    if reference:
        group.payment_reference = reference[:80]
    group.save(update_fields=["payment_status", "paid_at", "payment_reference", "updated_at"])
    return True
