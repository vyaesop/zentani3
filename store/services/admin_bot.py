"""The admin bot: who may use it, and the supplier review conversation.

Every webhook update goes through handle_update(). The owner (the
TELEGRAM_OWNER_USER_ID, or failing that the private TELEGRAM_ALERT_CHAT_ID)
and the admins they approve can work the review flow; anyone else can only
send /start to ask the owner for access.

Review flow, per supplier post (see store.services.supplier_intake):
  supplier photos -> summary with layout buttons -> one card per product
  -> "Add pictures" -> the admin's pictures -> published product.
Every admin gets their own copy of each message; TelegramBotMessage rows
remember where they went so claims and publishes update all copies.
"""
import html
import logging
import os
import time
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse
from django.utils import timezone

from store.models import (
    Category,
    SupplierItem,
    SupplierPost,
    TelegramBotAdmin,
    TelegramBotMessage,
)
from store.services import supplier_intake as intake
from store.telegram_notify import (
    _admin_bot_settings,
    _base_site_url,
    admin_bot_api,
    admin_bot_download_file,
    product_site_url,
)

logger = logging.getLogger(__name__)

PENDING_ACTION_TTL = timedelta(hours=1)
LAYOUT_LABELS = {
    SupplierPost.LAYOUT_SINGLE: "One product",
    SupplierPost.LAYOUT_COLOURS: "Colour variants",
    SupplierPost.LAYOUT_SEPARATE: "Separate products",
}
FIELD_LABELS = {
    "price": "price in ETB",
    "title": "title",
    "colour": "colour",
    "sizes": "sizes (comma separated, like S, M, L)",
    "desc": "short description",
}
# The house look, matching the AI studio shots already on the site.
COVER_PROMPT = (
    "Use the attached photo only as the reference for the garment and keep its exact cut, colour, "
    "fabric, print and details. Create a clean e-commerce product photo of this {garment} on an "
    "invisible ghost mannequin, front view, centred, the whole garment visible. Warm beige seamless "
    "studio backdrop, soft diffused light, gentle floor shadow, true-to-life colour. Portrait 3:4. "
    "No text, logos, watermarks, props or people."
)
MODEL_PROMPT = (
    "Now show the same {garment} worn by an Ethiopian woman model, full length, front view, natural "
    "relaxed pose, styled simply with neutral pieces so the garment stays the focus. Same warm beige "
    "seamless studio backdrop and soft light. Portrait 3:4. No text, logos or watermarks."
)


# ── Who may use the bot ────────────────────────────────────────────────────

def owner_user_id():
    for name in ("TELEGRAM_OWNER_USER_ID", "TELEGRAM_ALERT_CHAT_ID"):
        raw = (os.getenv(name) or "").strip()
        # Group chat ids are negative; only a person can own the bot.
        if raw.isdigit():
            return int(raw)
    return None


def _owner_admin():
    owner_id = owner_user_id()
    if owner_id is None:
        return None
    admin, _ = TelegramBotAdmin.objects.get_or_create(
        telegram_user_id=owner_id,
        defaults={"status": TelegramBotAdmin.STATUS_APPROVED, "full_name": "Owner"},
    )
    if admin.status != TelegramBotAdmin.STATUS_APPROVED:
        admin.status = TelegramBotAdmin.STATUS_APPROVED
        admin.save(update_fields=["status", "updated_at"])
    return admin


def is_owner(admin):
    return admin is not None and admin.telegram_user_id == owner_user_id()


def recipients():
    """Everyone who receives supplier reviews: the owner plus approved admins."""
    token, _ = _admin_bot_settings()
    if not token:
        return []
    owner = _owner_admin()
    admins = list(TelegramBotAdmin.objects.filter(status=TelegramBotAdmin.STATUS_APPROVED))
    if owner is not None and owner.pk not in {admin.pk for admin in admins}:
        admins.insert(0, owner)
    return admins


def _remember_profile(admin, user):
    username = (user.get("username") or "")[:64]
    full_name = " ".join(filter(None, [user.get("first_name"), user.get("last_name")]))[:150]
    if full_name and (admin.username != username or admin.full_name != full_name):
        admin.username = username
        admin.full_name = full_name
        admin.save(update_fields=["username", "full_name", "updated_at"])


def _admin_for(user):
    user_id = user.get("id")
    if not user_id:
        return None
    if user_id == owner_user_id():
        admin = _owner_admin()
    else:
        admin = TelegramBotAdmin.objects.filter(
            telegram_user_id=user_id, status=TelegramBotAdmin.STATUS_APPROVED
        ).first()
    if admin is not None:
        _remember_profile(admin, user)
    return admin


def _pending(admin):
    if not admin.pending_action or not admin.pending_action_at:
        return {}
    if admin.pending_action_at < timezone.now() - PENDING_ACTION_TTL:
        return {}
    return admin.pending_action


def _set_pending(admin, action):
    admin.pending_action = action or {}
    admin.pending_action_at = timezone.now() if action else None
    admin.save(update_fields=["pending_action", "pending_action_at", "updated_at"])


# ── Telegram plumbing ──────────────────────────────────────────────────────

def _esc(value):
    return html.escape(str(value or ""))


def _money(value):
    return f"{Decimal(value):,.0f}"


def _button(text, data=None, url=None):
    return {"text": text, "url": url} if url else {"text": text, "callback_data": data}


def _send(chat_id, text, *, markup=None, reply_to=None, force_reply_placeholder=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
    }
    if force_reply_placeholder is not None:
        payload["reply_markup"] = {"force_reply": True, "input_field_placeholder": force_reply_placeholder[:64]}
    elif markup:
        payload["reply_markup"] = markup
    if reply_to:
        payload["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
    return admin_bot_api("sendMessage", payload)


def _edit(chat_id, message_id, text, markup=None):
    return admin_bot_api(
        "editMessageText",
        {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
            "reply_markup": markup or {"inline_keyboard": []},
        },
    )


def _answer(callback_query, text=""):
    admin_bot_api("answerCallbackQuery", {"callback_query_id": callback_query.get("id"), "text": text[:200]})


def _record(result, *, chat_id, kind, post=None, item=None, photo_position=None):
    if not isinstance(result, dict) or not result.get("message_id"):
        return None
    row, _ = TelegramBotMessage.objects.get_or_create(
        chat_id=chat_id,
        message_id=result["message_id"],
        defaults={"kind": kind, "post": post, "item": item, "photo_position": photo_position},
    )
    return row


def _site_link(path_name, *args):
    base = _base_site_url()
    return f"{base}{reverse(path_name, args=args)}" if base else ""


# ── Post review (summary + layout buttons) ─────────────────────────────────

def _post_status_line(post):
    by = f" by {_esc(post.handled_by.display_name)}" if post.handled_by_id else ""
    if post.status == SupplierPost.STATUS_SENT:
        return "How should I list this?"
    if post.status in (SupplierPost.STATUS_LISTED, SupplierPost.STATUS_DONE):
        return f"✅ Listed as {LAYOUT_LABELS.get(post.layout, post.layout).lower()}{by}."
    if post.status == SupplierPost.STATUS_MANUAL:
        return f"🗂 Moved to the dashboard AI queue{by}."
    if post.status == SupplierPost.STATUS_SKIPPED:
        return f"⏭ Skipped{by}."
    if post.status == SupplierPost.STATUS_EXPIRED:
        return "⌛ Expired, probably sold by now."
    return ""


def post_summary_text(post):
    channel = post.channel
    analysis = post.analysis or {}
    items = analysis.get("items") or []
    lines = [
        f"🆕 <b>{_esc(channel.title or channel.username)}</b> · {post.posted_at:%d %b} · "
        f'<a href="{_esc(post.source_url)}">open post</a>'
    ]
    if post.caption:
        lines.append(f"<blockquote expandable>{_esc(post.caption[:900])}</blockquote>")
    names = "; ".join(
        _esc(entry.get("title")) + (f" ({_esc(entry['colour'])})" if entry.get("colour") else "")
        for entry in items[:6]
    )
    lines.append(f"🤖 Gemini sees {len(items)} item{'s' if len(items) != 1 else ''}: {names}")
    supplier_price = intake._first_price(items)
    if supplier_price is not None:
        lines.append(
            f"💰 Supplier {_money(supplier_price)} → <b>{_money(intake.retail_price(supplier_price, channel))} ETB</b>"
        )
    else:
        lines.append("💰 No price in the caption. Set it on each card.")
    if analysis.get("supplier_code"):
        lines.append(f"🏷 Supplier code: <code>{_esc(analysis['supplier_code'])}</code>")
    lines.append("")
    lines.append(_post_status_line(post))
    return "\n".join(lines)


def post_summary_markup(post):
    if post.status != SupplierPost.STATUS_SENT:
        return {"inline_keyboard": []}
    analysis = post.analysis or {}
    guess = analysis.get("layout_guess")

    def layout_button(layout):
        label = LAYOUT_LABELS[layout]
        return _button(f"✓ {label}" if layout == guess else label, f"L:{post.pk}:{layout}")

    rows = [[layout_button(SupplierPost.LAYOUT_SINGLE)]]
    if len(analysis.get("items") or []) > 1:
        rows.append([layout_button(SupplierPost.LAYOUT_COLOURS), layout_button(SupplierPost.LAYOUT_SEPARATE)])
    rows.append([_button("🗂 Dashboard", f"LD:{post.pk}"), _button("⏭ Skip", f"LS:{post.pk}")])
    return {"inline_keyboard": rows}


def _send_post_photos(chat_id, post, photos, photo_rows):
    """Send the supplier photos; uploads once, then reuses Telegram file ids."""
    files = []
    if len(photo_rows) == 1:
        row = photo_rows[0]
        if row.telegram_file_id:
            result = admin_bot_api("sendPhoto", {"chat_id": chat_id, "photo": row.telegram_file_id})
        else:
            content, mime = photos[0]
            result = admin_bot_api("sendPhoto", {"chat_id": chat_id}, files=[("photo", "photo0.jpg", content, mime)])
        messages = [result] if isinstance(result, dict) else []
    else:
        media = []
        for row in photo_rows:
            if row.telegram_file_id:
                media.append({"type": "photo", "media": row.telegram_file_id})
            else:
                content, mime = photos[row.position]
                media.append({"type": "photo", "media": f"attach://photo{row.position}"})
                files.append((f"photo{row.position}", f"photo{row.position}.jpg", content, mime))
        result = admin_bot_api("sendMediaGroup", {"chat_id": chat_id, "media": media}, files=files or None)
        messages = [message for message in result if isinstance(message, dict)] if isinstance(result, list) else []

    for row, message in zip(photo_rows, messages):
        sizes = message.get("photo") or []
        if sizes and not row.telegram_file_id:
            row.telegram_file_id = sizes[-1].get("file_id", "")
            row.save(update_fields=["telegram_file_id"])
        _record(message, chat_id=chat_id, kind=TelegramBotMessage.KIND_POST_PHOTO, post=post, photo_position=row.position)
    return messages


def send_post_review(post, photos):
    """Send a post's photos and summary to every admin. True if anyone got it."""
    photo_rows = list(post.photos.order_by("position"))
    delivered = False
    for admin in recipients():
        chat_id = admin.telegram_user_id
        try:
            messages = _send_post_photos(chat_id, post, photos, photo_rows)
            if not messages:
                continue
            summary = _send(
                chat_id,
                post_summary_text(post),
                markup=post_summary_markup(post),
                reply_to=messages[0]["message_id"],
            )
            if _record(summary, chat_id=chat_id, kind=TelegramBotMessage.KIND_POST, post=post):
                delivered = True
        except Exception:  # noqa: BLE001 - one admin's chat must not block the others.
            logger.exception("Sending supplier post %s to %s failed.", post.pk, chat_id)
    return delivered


def refresh_post_summaries(post):
    for row in TelegramBotMessage.objects.filter(post=post, kind=TelegramBotMessage.KIND_POST):
        _edit(row.chat_id, row.message_id, post_summary_text(post), post_summary_markup(post))


# ── Item cards ─────────────────────────────────────────────────────────────

def gemini_prompts(item):
    garment = (item.copy or {}).get("product_type") or item.title
    if item.color:
        garment = f"{garment} in {item.color}"
    return COVER_PROMPT.format(garment=garment), MODEL_PROMPT.format(garment=garment)


def _item_status_line(item):
    if item.status == SupplierItem.STATUS_PENDING:
        if item.claimed_by_id and item.claimed_at and item.claimed_at > timezone.now() - intake.CLAIM_TTL:
            return f"🙋 {_esc(item.claimed_by.display_name)} is adding pictures."
        return "📸 Waiting for pictures."
    if item.status == SupplierItem.STATUS_PUBLISHED:
        by = f" by {_esc(item.published_by.display_name)}" if item.published_by_id else ""
        return f"✅ Live on the site and the channel, published{by}."
    if item.status == SupplierItem.STATUS_UNPUBLISHED:
        return "🚫 Unpublished: hidden from the site, channel post deleted."
    if item.status == SupplierItem.STATUS_SKIPPED:
        return "⏭ Skipped."
    return "⌛ Expired, probably sold by now."


def item_card_text(item):
    total = item.post.items.count()
    head = f"<b>{item.position + 1}/{total} · {_esc(item.title)}</b>"
    if item.color:
        head += f" · {_esc(item.color)}"
    if item.price is not None:
        price_line = f"💰 <b>{_money(item.price)} ETB</b>"
        if item.supplier_price is not None:
            price_line += f" (supplier {_money(item.supplier_price)})"
    else:
        price_line = "⚠️ <b>No price yet.</b> Set it with Edit."
    category_line = f"🗂 {_esc(item.category.title)}" if item.category_id else "⚠️ <b>No collection yet.</b> Set it with Edit."
    lines = [
        head,
        price_line,
        f"📏 {_esc(item.sizes or ', '.join(intake.DEFAULT_SIZES))}",
        category_line,
        f"🏷 SKU: <code>{_esc(item.product.sku if item.product_id else intake.sku_base(item))}</code>",
    ]
    description = (item.copy or {}).get("short_description")
    if description:
        lines.append(f"📝 {_esc(description[:300])}")
    if item.status == SupplierItem.STATUS_PENDING:
        cover, on_model = gemini_prompts(item)
        lines += [
            "",
            "🎨 <b>Gemini prompts</b>. Tap one to copy it, then give Gemini the supplier photo above:",
            f"<code>{_esc(cover)}</code>",
            f"<code>{_esc(on_model)}</code>",
        ]
    lines += ["", _item_status_line(item)]
    return "\n".join(lines)


def item_card_markup(item):
    if item.status == SupplierItem.STATUS_PENDING:
        return {
            "inline_keyboard": [
                [_button("📸 Add pictures", f"P:{item.pk}")],
                [_button("✏️ Edit", f"E:{item.pk}"), _button("⏭ Skip", f"S:{item.pk}")],
            ]
        }
    if item.status == SupplierItem.STATUS_PUBLISHED and item.product_id:
        rows = []
        url = product_site_url(item.product)
        if url:
            rows.append([_button("🔗 View on site", url=url)])
        rows.append([_button("✏️ Edit", f"E:{item.pk}"), _button("🚫 Unpublish", f"U:{item.pk}")])
        return {"inline_keyboard": rows}
    if item.status == SupplierItem.STATUS_UNPUBLISHED:
        return {"inline_keyboard": [[_button("♻️ Republish", f"R:{item.pk}"), _button("✏️ Edit", f"E:{item.pk}")]]}
    return {"inline_keyboard": []}


def send_item_cards(post):
    chat_ids = list(
        TelegramBotMessage.objects.filter(post=post, kind=TelegramBotMessage.KIND_POST)
        .values_list("chat_id", flat=True)
        .distinct()
    )
    items = list(post.items.select_related("category", "post__channel", "claimed_by", "published_by"))
    for chat_id in chat_ids:
        photo_messages = dict(
            TelegramBotMessage.objects.filter(
                post=post, chat_id=chat_id, kind=TelegramBotMessage.KIND_POST_PHOTO
            ).values_list("photo_position", "message_id")
        )
        for item in items:
            first_photo = (item.photo_positions or [0])[0]
            result = _send(
                chat_id,
                item_card_text(item),
                markup=item_card_markup(item),
                reply_to=photo_messages.get(first_photo),
            )
            _record(result, chat_id=chat_id, kind=TelegramBotMessage.KIND_ITEM, item=item)


def refresh_item_cards(item):
    item = SupplierItem.objects.select_related(
        "category", "post__channel", "claimed_by", "published_by", "product"
    ).get(pk=item.pk)
    text, markup = item_card_text(item), item_card_markup(item)
    for row in TelegramBotMessage.objects.filter(item=item, kind=TelegramBotMessage.KIND_ITEM):
        _edit(row.chat_id, row.message_id, text, markup)


# ── Update entry point ─────────────────────────────────────────────────────

def handle_update(payload):
    if payload.get("callback_query"):
        _handle_callback(payload["callback_query"])
    elif payload.get("message"):
        _handle_message(payload["message"])


def welcome_text(admin):
    lines = [
        "🛠 <b>Zentanee admin bot</b>",
        "",
        "Order and signup alerts arrive here. Every morning new supplier posts arrive too:",
        "1. Pick how to list each post.",
        "2. Tap 📸 Add pictures on a card and send the pictures you made in Gemini, as files.",
        "3. The product goes live on the site and the channel as soon as they land.",
        "",
        "/cancel stops an edit or picture upload.",
    ]
    if is_owner(admin):
        lines.append("/admins shows who can use this bot.")
    return "\n".join(lines)


def _handle_message(message):
    chat = message.get("chat") or {}
    if chat.get("type") != "private":
        return
    chat_id = chat.get("id")
    user = message.get("from") or {}
    text = (message.get("text") or "").strip()
    admin = _admin_for(user)

    if text.startswith("/start") or text.startswith("/help"):
        if admin is not None:
            _send(chat_id, welcome_text(admin))
        else:
            _request_access(user, chat_id)
        return
    if admin is None:
        _send(chat_id, "This bot is private. Send /start to ask the owner for access.")
        return
    if text.startswith("/admins") and is_owner(admin):
        _send_admin_list(chat_id)
        return
    if text.startswith("/cancel"):
        _set_pending(admin, None)
        _send(chat_id, "Cancelled.")
        return
    if message.get("photo") or message.get("document"):
        _handle_picture(admin, message)
        return
    action = _pending(admin)
    if text and action.get("edit"):
        _handle_edit_value(admin, chat_id, action, text)
        return
    _send(chat_id, welcome_text(admin))


# ── Access requests ────────────────────────────────────────────────────────

def _request_access(user, chat_id):
    owner_id = owner_user_id()
    if owner_id is None:
        _send(chat_id, "This bot is private.")
        return
    record, created = TelegramBotAdmin.objects.get_or_create(
        telegram_user_id=user.get("id"),
        defaults={
            "username": (user.get("username") or "")[:64],
            "full_name": " ".join(filter(None, [user.get("first_name"), user.get("last_name")]))[:150],
        },
    )
    if record.status == TelegramBotAdmin.STATUS_DENIED:
        _send(chat_id, "The owner declined your access request.")
        return
    if record.status == TelegramBotAdmin.STATUS_PENDING and not created:
        _send(chat_id, "Your request is still waiting for the owner.")
        return
    if record.status == TelegramBotAdmin.STATUS_REMOVED:
        record.status = TelegramBotAdmin.STATUS_PENDING
        record.save(update_fields=["status", "updated_at"])

    handle = f" (@{_esc(record.username)})" if record.username else ""
    _send(
        owner_id,
        f"🙋 <b>{_esc(record.display_name)}</b>{handle} wants to use the admin bot.\n"
        "Admins can list, edit, publish and unpublish supplier products.",
        markup={
            "inline_keyboard": [[
                _button("✅ Approve", f"A:ok:{record.telegram_user_id}"),
                _button("❌ Deny", f"A:no:{record.telegram_user_id}"),
            ]]
        },
    )
    _send(chat_id, "Request sent. You'll get a message here once the owner approves it.")


def _send_admin_list(chat_id):
    owner_id = owner_user_id()
    people = list(
        TelegramBotAdmin.objects.filter(
            status__in=(TelegramBotAdmin.STATUS_APPROVED, TelegramBotAdmin.STATUS_PENDING)
        ).exclude(telegram_user_id=owner_id)
    )
    if not people:
        _send(chat_id, "Only you can use this bot. Others can ask for access by sending it /start.")
        return
    rows = []
    lines = ["<b>Bot admins</b>"]
    for person in people:
        if person.status == TelegramBotAdmin.STATUS_APPROVED:
            lines.append(f"• {_esc(person.display_name)}")
            rows.append([_button(f"🗑 Remove {person.display_name}"[:60], f"AR:{person.telegram_user_id}")])
        else:
            lines.append(f"• {_esc(person.display_name)} (waiting for approval)")
            rows.append([
                _button(f"✅ {person.display_name}"[:60], f"A:ok:{person.telegram_user_id}"),
                _button("❌ Deny", f"A:no:{person.telegram_user_id}"),
            ])
    _send(chat_id, "\n".join(lines), markup={"inline_keyboard": rows})


# ── Callbacks ──────────────────────────────────────────────────────────────

def _handle_callback(callback_query):
    admin = _admin_for(callback_query.get("from") or {})
    if admin is None:
        _answer(callback_query, "You don't have access to this bot.")
        return
    action, _, rest = (callback_query.get("data") or "").partition(":")
    handler = _CALLBACKS.get(action)
    if handler is None:
        _answer(callback_query)
        return
    try:
        toast = handler(admin, rest, callback_query)
    except intake.IntakeError as exc:
        toast = str(exc)
    except (ObjectDoesNotExist, ValueError):
        toast = "That item no longer exists."
    _answer(callback_query, toast or "")


def _callback_chat(callback_query):
    message = callback_query.get("message") or {}
    return (message.get("chat") or {}).get("id"), message.get("message_id")


def _cb_layout(admin, rest, callback_query):
    post_id, _, layout = rest.partition(":")
    if layout not in LAYOUT_LABELS:
        return "Unknown layout."
    post, _ = intake.choose_layout(SupplierPost.objects.get(pk=int(post_id)), layout, admin)
    refresh_post_summaries(post)
    send_item_cards(post)
    return f"Listed as {LAYOUT_LABELS[layout].lower()}."


def _cb_dashboard(admin, rest, callback_query):
    post, _ = intake.move_post_to_dashboard(SupplierPost.objects.get(pk=int(rest)), admin)
    refresh_post_summaries(post)
    chat_id, message_id = _callback_chat(callback_query)
    link = _site_link("dashboard-ai-queue")
    _send(chat_id, f"🗂 Saved as a draft in the dashboard AI queue.{chr(10) + link if link else ''}", reply_to=message_id)
    return "Moved to the dashboard."


def _cb_skip_post(admin, rest, callback_query):
    post = intake.skip_post(SupplierPost.objects.get(pk=int(rest)), admin)
    refresh_post_summaries(post)
    return "Skipped."


def _cb_add_pictures(admin, rest, callback_query):
    item, holder = intake.claim_item(SupplierItem.objects.get(pk=int(rest)), admin)
    if item.status != SupplierItem.STATUS_PENDING:
        return "This item is already published."
    if holder.pk != admin.pk:
        return f"{holder.display_name} is already adding pictures for this one."
    _set_pending(admin, {"pictures": item.pk})
    refresh_item_cards(item)
    chat_id, message_id = _callback_chat(callback_query)
    colour = f" ({_esc(item.color)})" if item.color else ""
    prompt = _send(
        chat_id,
        f"📸 Send the pictures for <b>{_esc(item.title)}</b>{colour} as a reply to this message.\n"
        "Send them as files (📎 → File) so Telegram doesn't compress them. "
        "The first picture becomes the cover. It goes live as soon as they arrive.",
        reply_to=message_id,
        force_reply_placeholder="Send the pictures",
    )
    _record(prompt, chat_id=chat_id, kind=TelegramBotMessage.KIND_PROMPT, item=item)
    return "Send the pictures."


def _cb_edit_menu(admin, rest, callback_query):
    item = SupplierItem.objects.get(pk=int(rest))
    if item.status in SupplierItem.CLOSED_STATUSES:
        return f"This item was {item.get_status_display().lower()}."
    chat_id, message_id = _callback_chat(callback_query)
    _send(
        chat_id,
        f"✏️ What should change on <b>{_esc(item.title)}</b>?",
        reply_to=message_id,
        markup={
            "inline_keyboard": [
                [_button("💰 Price", f"EF:{item.pk}:price"), _button("✏️ Title", f"EF:{item.pk}:title")],
                [_button("🎨 Colour", f"EF:{item.pk}:colour"), _button("📏 Sizes", f"EF:{item.pk}:sizes")],
                [_button("📝 Description", f"EF:{item.pk}:desc"), _button("🗂 Collection", f"EC:{item.pk}")],
                [_button("Done", "X:")],
            ]
        },
    )
    return ""


def _current_value(item, field):
    if field == "price":
        return _money(item.price) if item.price is not None else "not set"
    if field == "colour":
        return item.color or "none"
    if field == "desc":
        return (item.copy or {}).get("short_description") or "none"
    return getattr(item, field, "") or "none"


def _cb_edit_field(admin, rest, callback_query):
    item_id, _, field = rest.partition(":")
    if field not in FIELD_LABELS:
        return "Unknown field."
    item = SupplierItem.objects.get(pk=int(item_id))
    _set_pending(admin, {"edit": item.pk, "field": field})
    chat_id, message_id = _callback_chat(callback_query)
    _send(
        chat_id,
        f"Send the new {FIELD_LABELS[field]} for <b>{_esc(item.title)}</b>.\n"
        f"Now: {_esc(_current_value(item, field))}",
        reply_to=message_id,
        force_reply_placeholder=FIELD_LABELS[field],
    )
    return ""


def _cb_category_menu(admin, rest, callback_query):
    item = SupplierItem.objects.get(pk=int(rest))
    categories = list(Category.objects.filter(is_active=True).order_by("title")[:40])
    rows = []
    for start in range(0, len(categories), 2):
        rows.append([
            _button(category.title[:30], f"ECS:{item.pk}:{category.pk}")
            for category in categories[start:start + 2]
        ])
    chat_id, message_id = _callback_chat(callback_query)
    _edit(chat_id, message_id, f"🗂 Pick the collection for <b>{_esc(item.title)}</b>:", {"inline_keyboard": rows})
    return ""


def _cb_category_set(admin, rest, callback_query):
    item_id, _, category_id = rest.partition(":")
    item = intake.set_item_category(
        SupplierItem.objects.get(pk=int(item_id)),
        Category.objects.get(pk=int(category_id), is_active=True),
    )
    chat_id, message_id = _callback_chat(callback_query)
    _edit(chat_id, message_id, f"🗂 Collection set to <b>{_esc(item.category.title)}</b>.")
    refresh_item_cards(item)
    _publish_if_waiting(item, admin, chat_id)
    return "Collection set."


def _cb_done(admin, rest, callback_query):
    _set_pending(admin, None)
    chat_id, message_id = _callback_chat(callback_query)
    admin_bot_api("deleteMessage", {"chat_id": chat_id, "message_id": message_id})
    return ""


def _cb_skip_item(admin, rest, callback_query):
    item = intake.skip_item(SupplierItem.objects.get(pk=int(rest)), admin)
    refresh_item_cards(item)
    return "Skipped."


def _cb_unpublish(admin, rest, callback_query):
    item = SupplierItem.objects.select_related("product").get(pk=int(rest))
    channel_cleared = intake.unpublish_item(item)
    refresh_item_cards(item)
    if not channel_cleared:
        return "Unpublished, but Telegram refused to delete the channel post. Remove it by hand."
    return "Unpublished."


def _cb_republish(admin, rest, callback_query):
    item = SupplierItem.objects.select_related("product").get(pk=int(rest))
    intake.republish_item(item)
    refresh_item_cards(item)
    return "Republished."


def _cb_access(admin, rest, callback_query):
    if not is_owner(admin):
        return "Only the owner can approve admins."
    decision, _, user_id = rest.partition(":")
    person = TelegramBotAdmin.objects.filter(telegram_user_id=int(user_id)).first()
    if person is None or person.telegram_user_id == owner_user_id():
        return "Nothing to do."
    approved = decision == "ok"
    person.status = TelegramBotAdmin.STATUS_APPROVED if approved else TelegramBotAdmin.STATUS_DENIED
    person.save(update_fields=["status", "updated_at"])
    chat_id, message_id = _callback_chat(callback_query)
    verdict = "✅ Approved" if approved else "❌ Denied"
    _edit(chat_id, message_id, f"{verdict}: <b>{_esc(person.display_name)}</b>.")
    if approved:
        _send(person.telegram_user_id, "✅ You're in. Supplier posts will arrive here every morning.\n\n" + welcome_text(person))
    else:
        _send(person.telegram_user_id, "The owner declined your access request.")
    return verdict


def _cb_remove_admin(admin, rest, callback_query):
    if not is_owner(admin):
        return "Only the owner can remove admins."
    person = TelegramBotAdmin.objects.filter(telegram_user_id=int(rest)).first()
    if person is None or person.telegram_user_id == owner_user_id():
        return "The owner can't be removed."
    person.status = TelegramBotAdmin.STATUS_REMOVED
    person.pending_action = {}
    person.save(update_fields=["status", "pending_action", "updated_at"])
    _send(person.telegram_user_id, "Your access to the Zentanee admin bot was removed.")
    chat_id, _ = _callback_chat(callback_query)
    _send_admin_list(chat_id)
    return f"Removed {person.display_name}."


_CALLBACKS = {
    "L": _cb_layout,
    "LD": _cb_dashboard,
    "LS": _cb_skip_post,
    "P": _cb_add_pictures,
    "E": _cb_edit_menu,
    "EF": _cb_edit_field,
    "EC": _cb_category_menu,
    "ECS": _cb_category_set,
    "X": _cb_done,
    "S": _cb_skip_item,
    "U": _cb_unpublish,
    "R": _cb_republish,
    "A": _cb_access,
    "AR": _cb_remove_admin,
}


# ── Edits and pictures ─────────────────────────────────────────────────────

def _handle_edit_value(admin, chat_id, action, text):
    item = SupplierItem.objects.filter(pk=action.get("edit")).select_related("product").first()
    if item is None:
        _set_pending(admin, None)
        _send(chat_id, "That item no longer exists.")
        return
    try:
        intake.apply_edit(item, action.get("field"), text)
    except intake.IntakeError as exc:
        _send(chat_id, f"{_esc(exc)} Or send /cancel.")
        return
    _set_pending(admin, None)
    refresh_item_cards(item)
    _send(chat_id, f"✅ Updated <b>{_esc(item.title)}</b>.")
    _publish_if_waiting(item, admin, chat_id)


def _publish_if_waiting(item, admin, chat_id):
    """Pictures that arrived before the price/collection was set publish now."""
    item.refresh_from_db()
    if item.status != SupplierItem.STATUS_PENDING or not item.uploads.filter(attached=False).exists():
        return
    _publish(item, admin, chat_id)


def _publish(item, admin, chat_id, *, compressed=False):
    product, note = intake.publish_item(item, admin)
    refresh_item_cards(item)
    if product is None:
        _send(chat_id, note)
        return
    url = product_site_url(product)
    tip = "\n\nTip: send pictures as files (📎 → File) next time to keep full quality." if compressed else ""
    _send(
        chat_id,
        f"✅ <b>{_esc(product.title)}</b> is live at {_money(product.price)} ETB."
        + (f"\n{_esc(url)}" if url else "")
        + tip,
    )


def _item_for_picture(admin, message):
    reply = message.get("reply_to_message") or {}
    if reply.get("message_id"):
        row = (
            TelegramBotMessage.objects.filter(
                chat_id=(message.get("chat") or {}).get("id"),
                message_id=reply["message_id"],
                item__isnull=False,
            )
            .select_related("item")
            .first()
        )
        if row is not None:
            return row.item
    item_id = _pending(admin).get("pictures")
    return SupplierItem.objects.filter(pk=item_id).first() if item_id else None


def _handle_picture(admin, message):
    chat_id = (message.get("chat") or {}).get("id")
    item = _item_for_picture(admin, message)
    if item is None:
        _send(chat_id, "Tap 📸 Add pictures on a product card first, then send its pictures.")
        return
    if item.status in SupplierItem.CLOSED_STATUSES:
        _send(chat_id, f"That item was {item.get_status_display().lower()}, so the picture was not used.")
        return

    document = message.get("document")
    if document:
        if not (document.get("mime_type") or "").startswith("image/"):
            _send(chat_id, "Send pictures as JPG, PNG or WebP files.")
            return
        file_id, file_unique_id, compressed = document.get("file_id"), document.get("file_unique_id"), False
    else:
        largest = (message.get("photo") or [{}])[-1]
        file_id, file_unique_id, compressed = largest.get("file_id"), largest.get("file_unique_id"), True
    if not file_id or not file_unique_id:
        return

    content = admin_bot_download_file(file_id)
    if not content:
        _send(chat_id, "I couldn't download that picture (the limit is 20 MB). Try sending it again.")
        return
    try:
        upload, created = intake.store_upload(
            item, message_id=message.get("message_id") or 0, file_unique_id=file_unique_id, content=content
        )
    except intake.IntakeError as exc:
        _send(chat_id, _esc(exc))
        return
    if not created:
        return  # Telegram retried the webhook; this picture is already in.

    # An album arrives as one webhook call per picture. Wait for the rest so
    # the last call to land publishes the product with every picture.
    time.sleep(max(0, settings.SUPPLIER_PICTURE_SETTLE_SECONDS))
    newest = item.uploads.order_by("-pk").values_list("pk", flat=True).first()
    if newest != upload.pk:
        return
    item.refresh_from_db()
    if item.product_id:
        added = intake.attach_late_uploads(item)
        if added:
            _send(chat_id, f"➕ Added {added} picture{'s' if added != 1 else ''} to the gallery of <b>{_esc(item.title)}</b>.")
        return
    _publish(item, admin, chat_id, compressed=compressed)
