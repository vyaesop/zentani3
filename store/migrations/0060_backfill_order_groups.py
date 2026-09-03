"""Give every legacy order line an OrderGroup header.

Lines placed by the same customer in the same minute were one checkout, so
they share a group. Numbers use the first line's id (ZT-YYMMDD-L<id>) so they
are unique and stable; the contact snapshot is reconstructed from the guest
contact or the customer's most recent saved address.
"""
import secrets

from django.db import migrations


def forwards(apps, schema_editor):
    Order = apps.get_model("store", "Order")
    OrderGroup = apps.get_model("store", "OrderGroup")
    Address = apps.get_model("store", "Address")

    groups_by_key = {}
    lines = (
        Order.objects.filter(group__isnull=True)
        .select_related("user")
        .order_by("ordered_date", "id")
    )
    for order in lines:
        stamp = order.ordered_date.strftime("%Y%m%d%H%M") if order.ordered_date else f"id{order.id}"
        key = (order.user_id, order.session_key or "", stamp)
        group = groups_by_key.get(key)
        if group is None:
            contact = {}
            if order.guest_contact:
                contact = {k: (v or "") for k, v in dict(order.guest_contact).items()}
            elif order.user_id:
                user = order.user
                latest_address = Address.objects.filter(user_id=order.user_id).order_by("-id").first()
                contact = {
                    "full_name": f"{user.first_name} {user.last_name}".strip() or user.username,
                    "phone": (latest_address.phone if latest_address else "") or user.username,
                    "city": latest_address.city if latest_address else "",
                    "address": latest_address.address if latest_address else "",
                    "email": user.email or "",
                }
            date_part = order.ordered_date.strftime("%y%m%d") if order.ordered_date else "000000"
            group = OrderGroup.objects.create(
                number=f"ZT-{date_part}-L{order.id}",
                user_id=order.user_id,
                session_key=order.session_key or "",
                claim_token=secrets.token_urlsafe(24),
                contact=contact,
                payment_method="cod",
                payment_status="unpaid",
            )
            if order.ordered_date:
                OrderGroup.objects.filter(pk=group.pk).update(created_at=order.ordered_date, updated_at=order.ordered_date)
            groups_by_key[key] = group
        order.group = group
        order.save(update_fields=["group"])

    for group in groups_by_key.values():
        subtotal = sum((line.line_total or 0) for line in Order.objects.filter(group=group))
        OrderGroup.objects.filter(pk=group.pk).update(subtotal=subtotal, total=subtotal)


def backwards(apps, schema_editor):
    Order = apps.get_model("store", "Order")
    OrderGroup = apps.get_model("store", "OrderGroup")
    Order.objects.update(group=None)
    OrderGroup.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("store", "0059_order_groups_reviews_seo_fields"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
