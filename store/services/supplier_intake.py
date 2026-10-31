"""Supplier channel intake: scrape, let Gemini read, review in the admin bot, publish.

Daily (`manage.py supplier_intake`, run by .github/workflows/supplier-intake.yml):
  1. ingest_channel - new photo posts since the last run become SupplierPosts.
  2. expire_stale - review cards nobody acted on expire (stock moves fast).
  3. send_reviews - the newest posts, up to SUPPLIER_REVIEW_DAILY_LIMIT, are
     read by Gemini and sent to every bot admin with layout buttons.
Then, driven by the admin bot webhook (store.services.admin_bot):
  4. choose_layout turns a post into SupplierItems, one per product.
  5. An admin's pictures arrive and publish_item creates the live Product,
     which posts to the channel; unpublish_item takes both down again.

Products are only created at step 5, so the catalog never holds a
half-finished import.
"""
import io
import logging
from datetime import datetime, time as dt_time, timedelta
from decimal import ROUND_CEILING, Decimal, InvalidOperation

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from store.models import (
    BackgroundTask,
    Category,
    Product,
    ProductAIDraft,
    ProductImages,
    SupplierChannel,
    SupplierItem,
    SupplierItemUpload,
    SupplierPost,
    SupplierPostPhoto,
)
from store.services import supplier_scraper
from store.services.color_variants import link_products, unique_product_sku, unique_product_slug
from store.services.enrichment import resolve_taxonomy
from store.services.inventory import parse_size_list, set_product_sizes
from store.services.supplier_ai import analyze_post, taxonomy_payload
from store.tasks import enqueue
from store.telegram_notify import delete_product_channel_posts, suspend_telegram_autopublish

try:
    from PIL import Image
except ImportError:  # pragma: no cover - Pillow is a hard dependency in practice.
    Image = None

logger = logging.getLogger(__name__)

MAX_ANALYSIS_ATTEMPTS = 3
# A repost of a caption we handled this recently is the same stock, not news.
REPOST_LOOKBACK_DAYS = 60
# Another admin's "Add pictures" claim blocks others for this long.
CLAIM_TTL = timedelta(hours=2)
DEFAULT_SIZES = ["One size"]
COPY_KEYS = (
    "product_type",
    "short_description",
    "detail_description",
    "material",
    "fit_notes",
    "care_notes",
    "seo_title",
    "seo_description",
    "image_alt_text",
)


class IntakeError(Exception):
    """A user-facing reason an intake action could not happen."""


# ── Pricing ────────────────────────────────────────────────────────────────

def retail_price(supplier_price, channel):
    """supplier + delivery cover + max(min profit, markup %), rounded up.

    With the defaults (500 delivery, 25%, 300 floor, round to 100):
    835 -> 1,700 and 1,600 -> 2,500.
    """
    if supplier_price in (None, ""):
        return None
    cost = Decimal(str(supplier_price))
    profit = max(Decimal(channel.min_profit), cost * Decimal(channel.markup_percent) / Decimal(100))
    raw = cost + Decimal(channel.delivery_cover) + profit
    step = Decimal(channel.round_to or 1)
    return (raw / step).to_integral_value(rounding=ROUND_CEILING) * step


def parse_price(text):
    """Admin-typed price ("1800", "1,800 birr", "ETB 1800.50") -> Decimal."""
    cleaned = "".join(ch for ch in str(text or "") if ch.isdigit() or ch == ".")
    try:
        amount = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        raise IntakeError("Send the price as a number, like 1800.")
    if amount <= 0 or amount >= Decimal("1000000"):
        raise IntakeError("That price looks wrong. Send a number like 1800.")
    return amount.quantize(Decimal("1"))


# ── 1. Scraping ────────────────────────────────────────────────────────────

def _db_datetime(aware):
    """The scraper's aware timestamps in the form the database expects
    (naive store-local time while USE_TZ is off)."""
    if settings.USE_TZ:
        return aware
    return timezone.make_naive(aware, timezone.get_default_timezone())


def _first_photo_fingerprint(photo_urls):
    for url in photo_urls[:1]:
        try:
            return supplier_scraper.photo_fingerprint(supplier_scraper.download(url))
        except Exception:  # noqa: BLE001 - no fingerprint just means no repost check.
            logger.warning("Could not fingerprint %s", url)
    return ""


def _bump_to_repost(post, listing):
    """A repost of a post still waiting to be sent: keep one row, but make it
    the newest copy, since a fresh repost is the best sign it is in stock."""
    post.message_ids = sorted(set(post.message_ids or []) | set(listing.message_ids))
    post.message_id = listing.message_id
    post.posted_at = _db_datetime(listing.posted_at)
    post.caption = listing.caption
    post.caption_hash = supplier_scraper.caption_hash(listing.caption)
    post.photo_urls = listing.photo_urls
    post.save(update_fields=["message_ids", "message_id", "posted_at", "caption", "caption_hash", "photo_urls", "updated_at"])


def ingest_channel(channel, *, now=None, fetch=supplier_scraper.fetch_preview_page, sleep=None):
    """Store the channel's new photo listings. Returns how many were created."""
    now = now or timezone.now()
    since = datetime.combine(channel.scrape_since, dt_time.min, tzinfo=timezone.get_default_timezone())
    kwargs = {"fetch": fetch}
    if sleep is not None:
        kwargs["sleep"] = sleep
    messages = supplier_scraper.fetch_new_messages(
        channel.username, after_id=channel.last_message_id, since=since, **kwargs
    )

    created = 0
    recent = list(
        SupplierPost.objects.filter(
            channel=channel,
            created_at__gte=now - timedelta(days=REPOST_LOOKBACK_DAYS),
            status__in=SupplierPost.REPOST_BLOCKING_STATUSES,
        ).exclude(photo_hash="")
    )
    for listing in supplier_scraper.group_listings(messages):
        if SupplierPost.objects.filter(channel=channel, message_id=listing.message_id).exists():
            continue
        fingerprint = _first_photo_fingerprint(listing.photo_urls)
        original = next(
            (post for post in recent if supplier_scraper.fingerprints_match(post.photo_hash, fingerprint)),
            None,
        )
        if original is not None:
            if original.status == SupplierPost.STATUS_NEW:
                _bump_to_repost(original, listing)
            continue  # The same stock, already listed or waiting for review.
        post = SupplierPost.objects.create(
            channel=channel,
            message_id=listing.message_id,
            message_ids=listing.message_ids,
            posted_at=_db_datetime(listing.posted_at),
            caption=listing.caption,
            caption_hash=supplier_scraper.caption_hash(listing.caption),
            photo_hash=fingerprint,
            photo_urls=listing.photo_urls,
        )
        if fingerprint:
            recent.append(post)
        created += 1

    if messages:
        channel.last_message_id = max(channel.last_message_id, max(m.message_id for m in messages))
    channel.last_scraped_at = now
    channel.last_error = ""
    channel.save(update_fields=["last_message_id", "last_scraped_at", "last_error", "updated_at"])
    return created


def mark_on_site(channel_username, message_id, note=""):
    """Record that a scraped post is already on the site, so it is never sent
    for review and its reposts are ignored. `message_id` may be any of the
    post's message ids (a repost bump keeps them all)."""
    for post in SupplierPost.objects.filter(channel__username=channel_username):
        if message_id == post.message_id or message_id in (post.message_ids or []):
            post.status = SupplierPost.STATUS_ON_SITE
            post.error = (f"Already on the site: {note}" if note else "Already on the site.")[:250]
            post.save(update_fields=["status", "error", "updated_at"])
            return post
    raise IntakeError(f"No scraped post {channel_username}/{message_id}.")


# ── 2. Expiry ──────────────────────────────────────────────────────────────

def expire_stale(*, now=None):
    """Expire review cards nobody acted on, and posts too old to still be in stock."""
    from store.services import admin_bot

    now = now or timezone.now()
    review_cutoff = now - timedelta(days=settings.SUPPLIER_REVIEW_EXPIRY_DAYS)
    expired = 0

    for item in SupplierItem.objects.filter(
        status=SupplierItem.STATUS_PENDING, post__sent_at__lt=review_cutoff
    ).select_related("post"):
        item.status = SupplierItem.STATUS_EXPIRED
        item.save(update_fields=["status", "updated_at"])
        admin_bot.refresh_item_cards(item)
        finish_post_if_done(item.post)
        expired += 1

    for post in SupplierPost.objects.filter(status=SupplierPost.STATUS_SENT, sent_at__lt=review_cutoff):
        post.status = SupplierPost.STATUS_EXPIRED
        post.save(update_fields=["status", "updated_at"])
        admin_bot.refresh_post_summaries(post)
        expired += 1

    age_cutoff = now - timedelta(days=settings.SUPPLIER_POST_MAX_AGE_DAYS)
    expired += SupplierPost.objects.filter(
        status__in=(SupplierPost.STATUS_NEW, SupplierPost.STATUS_FAILED), posted_at__lt=age_cutoff
    ).update(status=SupplierPost.STATUS_EXPIRED, updated_at=now)
    return expired


# ── 3. Gemini reading + review messages ────────────────────────────────────

def _image_mime(content):
    if Image is None:
        return "image/jpeg"
    try:
        with Image.open(io.BytesIO(content)) as image:
            return Image.MIME.get(image.format, "image/jpeg")
    except Exception:  # noqa: BLE001 - an unreadable photo is reported by the caller.
        return None


def download_post_photos(post):
    """[(bytes, mime)] for the post's photos, refreshing stale CDN URLs once."""
    urls = list(post.photo_urls or [])
    photos = []
    refreshed = False
    position = 0
    while position < len(urls):
        try:
            content = supplier_scraper.download(urls[position])
            mime = _image_mime(content)
            if not mime:
                raise ValueError("not an image")
        except Exception:  # noqa: BLE001 - CDN links can expire; retry with fresh ones.
            if refreshed:
                raise
            fresh = supplier_scraper.refresh_photo_urls(post.channel.username, post.message_id)
            refreshed = True
            if len(fresh) >= len(urls):
                urls = fresh[: len(urls)]
                post.photo_urls = urls
                post.save(update_fields=["photo_urls", "updated_at"])
            continue
        photos.append((content, mime))
        position += 1
    return photos


def analyze_and_send(post):
    """Read one post with Gemini and send it for review. Returns True when sent."""
    from store.services import admin_bot

    photos = download_post_photos(post)
    analysis = analyze_post(
        channel_title=post.channel.title or post.channel.username,
        caption=post.caption,
        photos=photos,
        collection_options=list(Category.objects.filter(is_active=True).order_by("title")),
    )
    post.analysis = analysis
    if not analysis["is_product_post"]:
        post.status = SupplierPost.STATUS_SKIPPED
        post.error = analysis["skip_reason"][:250]
        post.save(update_fields=["analysis", "status", "error", "updated_at"])
        return False

    SupplierPostPhoto.objects.filter(post=post).delete()
    SupplierPostPhoto.objects.bulk_create(
        SupplierPostPhoto(post=post, position=index, source_url=url[:1000])
        for index, url in enumerate(post.photo_urls)
    )
    # Marked sent before rendering: the summary only shows layout buttons
    # for a post in the "sent" state. A failed delivery is reset by the caller.
    post.status = SupplierPost.STATUS_SENT
    post.sent_at = timezone.now()
    post.error = ""
    post.save(update_fields=["analysis", "status", "sent_at", "error", "updated_at"])
    if not admin_bot.send_post_review(post, photos):
        post.sent_at = None
        post.save(update_fields=["sent_at", "updated_at"])
        raise IntakeError("The admin bot could not deliver the review.")
    return True


def send_reviews(*, now=None, limit=None, log=None):
    """Send the newest unsent posts, keeping to the daily limit. Returns the count sent."""
    from store.services import admin_bot

    now = now or timezone.now()
    log = log or (lambda message: None)
    if not admin_bot.recipients():
        log("No bot admins to send reviews to (set TELEGRAM_BOT_TOKEN and TELEGRAM_ALERT_CHAT_ID).")
        return 0
    limit = settings.SUPPLIER_REVIEW_DAILY_LIMIT if limit is None else limit
    # 20h, not 24h: GitHub's cron drifts, and tomorrow's run must not find
    # today's batch still inside its window.
    already_sent = SupplierPost.objects.filter(sent_at__gte=now - timedelta(hours=20)).count()
    quota = max(0, limit - already_sent)

    sent = 0
    candidates = SupplierPost.objects.filter(
        status__in=(SupplierPost.STATUS_NEW, SupplierPost.STATUS_FAILED),
        attempts__lt=MAX_ANALYSIS_ATTEMPTS,
        posted_at__gte=now - timedelta(days=settings.SUPPLIER_POST_MAX_AGE_DAYS),
    ).select_related("channel").order_by("-posted_at")
    for post in candidates:
        if sent >= quota:
            break
        post.attempts += 1
        post.save(update_fields=["attempts", "updated_at"])
        try:
            if analyze_and_send(post):
                sent += 1
                log(f"Sent {post} for review.")
            else:
                log(f"Skipped {post}: {post.error}")
        except Exception as exc:  # noqa: BLE001 - one bad post must not stop the batch.
            logger.exception("Supplier post %s failed.", post)
            post.status = SupplierPost.STATUS_FAILED
            post.error = f"{type(exc).__name__}: {exc}"[:250]
            post.save(update_fields=["status", "error", "updated_at"])
            log(f"Failed {post}: {post.error}")
    return sent


def run_daily(*, now=None, log=None, fetch=supplier_scraper.fetch_preview_page, sleep=None):
    """The whole daily pass. Returns a summary dict."""
    log = log or (lambda message: None)
    summary = {"created": 0, "expired": 0, "sent": 0, "errors": []}
    for channel in SupplierChannel.objects.filter(is_active=True):
        try:
            created = ingest_channel(channel, now=now, fetch=fetch, sleep=sleep)
        except Exception as exc:  # noqa: BLE001 - a dead channel must not block the others.
            logger.exception("Scraping %s failed.", channel.username)
            channel.last_error = f"{type(exc).__name__}: {exc}"[:250]
            channel.save(update_fields=["last_error", "updated_at"])
            summary["errors"].append(f"{channel.username}: {channel.last_error}")
            log(f"{channel.username}: scrape failed ({channel.last_error})")
            continue
        summary["created"] += created
        log(f"{channel.username}: {created} new listing(s).")
    summary["expired"] = expire_stale(now=now)
    summary["sent"] = send_reviews(now=now, log=log)
    return summary


# ── 4. Layout -> items ─────────────────────────────────────────────────────

def _first_price(entries):
    for entry in entries:
        if entry.get("supplier_price"):
            return Decimal(str(entry["supplier_price"]))
    return None


def _create_item(post, position, base, *, color, photos, supplier_price, sizes, group_key):
    category, _ = resolve_taxonomy(taxonomy_payload(base), "collection")
    return SupplierItem.objects.create(
        post=post,
        position=position,
        group_key=group_key,
        title=(base.get("title") or "Untitled piece")[:150],
        color=(color or "")[:80],
        sizes=", ".join(sizes)[:200],
        supplier_price=supplier_price,
        price=retail_price(supplier_price, post.channel),
        category=category,
        copy={key: base.get(key, "") for key in COPY_KEYS},
        photo_positions=sorted(photos),
    )


def build_items(post, layout):
    entries = list((post.analysis or {}).get("items") or [])
    if not entries:
        raise IntakeError("Gemini found no items in this post.")
    fallback_price = _first_price(entries)
    all_photos = list(range(len(post.photo_urls or [])))

    def price_of(entry):
        return Decimal(str(entry["supplier_price"])) if entry.get("supplier_price") else fallback_price

    if layout == SupplierPost.LAYOUT_SINGLE or len(entries) == 1:
        base = entries[0]
        colours = {entry.get("colour", "").casefold() for entry in entries if entry.get("colour")}
        sizes = base.get("sizes") or next((entry["sizes"] for entry in entries if entry.get("sizes")), [])
        return [
            _create_item(
                post, 0, base,
                color=base.get("colour", "") if len(colours) <= 1 else "",
                photos=all_photos,
                supplier_price=price_of(base),
                sizes=sizes,
                group_key="",
            )
        ]

    if layout == SupplierPost.LAYOUT_COLOURS:
        # One garment: every colour shares the first item's copy.
        base = entries[0]
        return [
            _create_item(
                post, index, base,
                color=entry.get("colour", ""),
                photos=entry.get("photos") or all_photos,
                supplier_price=price_of(entry),
                sizes=entry.get("sizes") or base.get("sizes") or [],
                group_key=f"post-{post.pk}",
            )
            for index, entry in enumerate(entries)
        ]

    if layout == SupplierPost.LAYOUT_SEPARATE:
        garment_counts = {}
        for entry in entries:
            garment_counts[entry.get("garment")] = garment_counts.get(entry.get("garment"), 0) + 1
        return [
            _create_item(
                post, index, entry,
                color=entry.get("colour", ""),
                photos=entry.get("photos") or all_photos,
                supplier_price=price_of(entry),
                sizes=entry.get("sizes") or [],
                # Same garment in several colours still links as siblings.
                group_key=f"post-{post.pk}-{entry.get('garment')}" if garment_counts[entry.get("garment")] > 1 else "",
            )
            for index, entry in enumerate(entries)
        ]

    raise IntakeError(f"Unknown layout {layout!r}.")


def choose_layout(post, layout, admin):
    """Turn a reviewed post into items. Raises IntakeError if someone beat us to it."""
    with transaction.atomic():
        locked = SupplierPost.objects.select_for_update().select_related("channel").get(pk=post.pk)
        if locked.status != SupplierPost.STATUS_SENT:
            raise IntakeError("This post was already handled.")
        items = build_items(locked, layout)
        locked.layout = layout
        locked.status = SupplierPost.STATUS_LISTED
        locked.handled_by = admin
        locked.save(update_fields=["layout", "status", "handled_by", "updated_at"])
    return locked, items


def skip_post(post, admin):
    updated = SupplierPost.objects.filter(pk=post.pk, status=SupplierPost.STATUS_SENT).update(
        status=SupplierPost.STATUS_SKIPPED, handled_by=admin, updated_at=timezone.now()
    )
    if not updated:
        raise IntakeError("This post was already handled.")
    post.refresh_from_db()
    return post


def _draft_owner():
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return (
        User.objects.filter(is_superuser=True).order_by("id").first()
        or User.objects.filter(is_staff=True).order_by("id").first()
    )


def _supplier_photo_bytes(photo):
    from store.telegram_notify import admin_bot_download_file

    if photo.telegram_file_id:
        content = admin_bot_download_file(photo.telegram_file_id)
        if content:
            return content
    return supplier_scraper.download(photo.source_url)


def move_post_to_dashboard(post, admin):
    """Hand a messy post to the dashboard's AI queue as an idle draft."""
    owner = _draft_owner()
    if owner is None:
        raise IntakeError("No staff account exists to own the dashboard draft.")
    with transaction.atomic():
        locked = SupplierPost.objects.select_for_update().select_related("channel").get(pk=post.pk)
        if locked.status != SupplierPost.STATUS_SENT:
            raise IntakeError("This post was already handled.")
        entries = (locked.analysis or {}).get("items") or []
        sizes = next((entry["sizes"] for entry in entries if entry.get("sizes")), [])
        draft = ProductAIDraft(
            created_by=owner,
            sku=unique_product_sku(f"{locked.channel.sku_prefix}-{locked.message_id}"),
            vendor_hint=(locked.channel.title or locked.channel.username)[:120],
            price=retail_price(_first_price(entries), locked.channel),
            sizes=", ".join(sizes)[:100],
        )
        photos = list(locked.photos.all()[:2])
        for photo, field_name in zip(photos, ("reference_image", "secondary_reference_image")):
            content = _supplier_photo_bytes(photo)
            getattr(draft, field_name).save(f"{draft.sku}-{photo.position}.jpg", ContentFile(content), save=False)
        draft.save()
        locked.status = SupplierPost.STATUS_MANUAL
        locked.handled_by = admin
        locked.save(update_fields=["status", "handled_by", "updated_at"])
    return locked, draft


# ── 5. Pictures, publishing, edits ─────────────────────────────────────────

def missing_for_publish(item):
    missing = []
    if item.price is None:
        missing.append("price")
    if item.category_id is None:
        missing.append("collection")
    return missing


def claim_item(item, admin, *, now=None):
    """Mark `admin` as the one adding pictures. Returns the current holder."""
    now = now or timezone.now()
    with transaction.atomic():
        locked = SupplierItem.objects.select_for_update().get(pk=item.pk)
        if locked.status in SupplierItem.CLOSED_STATUSES:
            raise IntakeError(f"This item was {locked.get_status_display().lower()}.")
        held_by_other = (
            locked.claimed_by_id
            and locked.claimed_by_id != admin.pk
            and locked.claimed_at
            and locked.claimed_at > now - CLAIM_TTL
            and locked.status == SupplierItem.STATUS_PENDING
        )
        if held_by_other:
            return locked, locked.claimed_by
        locked.claimed_by = admin
        locked.claimed_at = now
        locked.save(update_fields=["claimed_by", "claimed_at", "updated_at"])
    return locked, admin


def sku_base(item):
    """ADT-3047, or ADT-3047-2 when one post became several products.

    The supplier's message id in the SKU means an order alert leads straight
    back to t.me/<channel>/<id> when it is time to buy from the supplier.
    """
    base = f"{item.post.channel.sku_prefix}-{item.post.message_id}"
    if item.post.items.count() > 1:
        base = f"{base}-{item.position + 1}"
    return base


def item_sku(item):
    return unique_product_sku(sku_base(item))


def store_upload(item, *, message_id, file_unique_id, content):
    """Save one admin picture. Returns (upload, created); never stores a file twice."""
    existing = SupplierItemUpload.objects.filter(file_unique_id=file_unique_id).first()
    if existing is not None:
        return existing, False
    extension = "jpg"
    if Image is not None:
        try:
            with Image.open(io.BytesIO(content)) as image:
                image.verify()
                extension = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}.get(image.format, "")
        except Exception:  # noqa: BLE001
            extension = ""
        if not extension:
            raise IntakeError("That file is not a JPG, PNG or WebP picture.")
    upload = SupplierItemUpload(item=item, telegram_message_id=message_id, file_unique_id=file_unique_id)
    upload.image.save(f"{sku_base(item).lower()}-{message_id}.{extension}", ContentFile(content), save=False)
    upload.save()
    return upload, True


def _queue_channel_post(product):
    enqueue(BackgroundTask.TYPE_TELEGRAM_PRODUCT_POST, {"product_id": product.id, "force": True})


def attach_late_uploads(item):
    """Add pictures that arrived after publishing to the gallery. Returns the count."""
    uploads = list(item.uploads.filter(attached=False))
    if not uploads or not item.product_id:
        return 0
    with transaction.atomic(), suspend_telegram_autopublish():
        for upload in uploads:
            ProductImages.objects.create(product=item.product, image=upload.image.name)
        SupplierItemUpload.objects.filter(pk__in=[upload.pk for upload in uploads]).update(attached=True)
    return len(uploads)


def publish_item(item, admin):
    """Create the live product from an item and its pictures.

    Returns (product, note). `product` is None when something is still
    missing; the note says what. Safe to call concurrently: only the first
    caller creates the product, later ones attach any extra pictures.
    """
    missing = missing_for_publish(item)
    if missing:
        return None, f"Pictures saved. Set the {' and '.join(missing)} with Edit and it publishes straight away."

    with transaction.atomic():
        locked = SupplierItem.objects.select_for_update().select_related("post__channel", "category").get(pk=item.pk)
        if locked.product_id:
            added = attach_late_uploads(locked)
            return None, f"Added {added} picture(s) to the gallery." if added else "Already published."
        uploads = list(locked.uploads.filter(attached=False).order_by("telegram_message_id"))
        if not uploads:
            return None, "Send the pictures first."

        copy = locked.copy or {}
        title = locked.title
        with suspend_telegram_autopublish():
            product = Product(
                title=title,
                slug=unique_product_slug(f"{title} {locked.color}" if locked.color and locked.color.casefold() not in title.casefold() else title),
                sku=item_sku(locked),
                short_description=copy.get("short_description") or title,
                detail_description=copy.get("detail_description") or "",
                seo_title=(copy.get("seo_title") or "")[:180],
                seo_description=(copy.get("seo_description") or "")[:320],
                image_alt_text=(copy.get("image_alt_text") or (f"{title} in {locked.color}" if locked.color else title))[:180],
                material=(copy.get("material") or "")[:120],
                color=locked.color,
                fit_notes=copy.get("fit_notes") or "",
                care_notes=copy.get("care_notes") or "",
                price=locked.price,
                category=locked.category,
                brand=None,
                is_active=True,
                is_featured=False,
                is_sold_out=False,
            )
            product.product_image.name = uploads[0].image.name
            product.save()
            for upload in uploads[1:]:
                ProductImages.objects.create(product=product, image=upload.image.name)
            set_product_sizes(product, parse_size_list(locked.sizes) or DEFAULT_SIZES)

            if locked.group_key:
                sibling = (
                    SupplierItem.objects.filter(post=locked.post, group_key=locked.group_key, product__isnull=False)
                    .exclude(pk=locked.pk)
                    .select_related("product")
                    .first()
                )
                if sibling is not None:
                    link_products(sibling.product, product)

            SupplierItemUpload.objects.filter(pk__in=[upload.pk for upload in uploads]).update(attached=True)
            locked.product = product
            locked.status = SupplierItem.STATUS_PUBLISHED
            locked.published_by = admin
            locked.save(update_fields=["product", "status", "published_by", "updated_at"])
        _queue_channel_post(product)

    finish_post_if_done(locked.post)
    return product, ""


def finish_post_if_done(post):
    open_items = post.items.filter(status=SupplierItem.STATUS_PENDING).exists()
    if not open_items and post.status == SupplierPost.STATUS_LISTED:
        post.status = SupplierPost.STATUS_DONE
        post.save(update_fields=["status", "updated_at"])


def skip_item(item, admin):
    updated = SupplierItem.objects.filter(pk=item.pk, status=SupplierItem.STATUS_PENDING).update(
        status=SupplierItem.STATUS_SKIPPED, updated_at=timezone.now()
    )
    if not updated:
        raise IntakeError("Only items still waiting for pictures can be skipped.")
    item.refresh_from_db()
    finish_post_if_done(item.post)
    return item


def unpublish_item(item):
    """Hide the product and delete its channel posts."""
    if not item.product_id or item.status != SupplierItem.STATUS_PUBLISHED:
        raise IntakeError("Only published items can be unpublished.")
    product = item.product
    with suspend_telegram_autopublish():
        product.is_active = False
        product.save(update_fields=["is_active", "updated_at"])
    channel_cleared = delete_product_channel_posts(product)
    item.status = SupplierItem.STATUS_UNPUBLISHED
    item.save(update_fields=["status", "updated_at"])
    return channel_cleared


def republish_item(item):
    if not item.product_id or item.status != SupplierItem.STATUS_UNPUBLISHED:
        raise IntakeError("Only unpublished items can be republished.")
    product = item.product
    with suspend_telegram_autopublish():
        product.is_active = True
        product.save(update_fields=["is_active", "updated_at"])
    _queue_channel_post(product)
    item.status = SupplierItem.STATUS_PUBLISHED
    item.save(update_fields=["status", "updated_at"])


EDITABLE_FIELDS = {
    "price": "price",
    "title": "title",
    "colour": "colour",
    "sizes": "sizes",
    "desc": "description",
}


def apply_edit(item, field, value):
    """Apply an admin's edit to the item (and its live product, if any)."""
    value = (value or "").strip()
    if field == "price":
        item.price = parse_price(value)
    elif field == "title":
        if not 3 <= len(value) <= 150:
            raise IntakeError("Titles need 3 to 150 characters.")
        item.title = value
    elif field == "colour":
        if len(value) > 80:
            raise IntakeError("Keep the colour under 80 characters.")
        item.color = value
    elif field == "sizes":
        sizes = parse_size_list(value)
        if not sizes:
            raise IntakeError("Send the sizes separated by commas, like S, M, L.")
        item.sizes = ", ".join(sizes)[:200]
    elif field == "desc":
        if len(value) < 10:
            raise IntakeError("The description needs at least 10 characters.")
        item.copy = {**(item.copy or {}), "short_description": value[:1000]}
    else:
        raise IntakeError("Unknown field.")
    item.save()
    _sync_live_product(item, field)
    return item


def set_item_category(item, category):
    item.category = category
    item.save(update_fields=["category", "updated_at"])
    _sync_live_product(item, "category")
    return item


def _sync_live_product(item, field):
    """Mirror an edit onto the published product and refresh its channel post."""
    if not item.product_id:
        return
    product = item.product
    with suspend_telegram_autopublish():
        if field == "price":
            product.price = item.price
        elif field == "title":
            product.title = item.title
        elif field == "colour":
            product.color = item.color
        elif field == "desc":
            product.short_description = item.copy.get("short_description") or product.short_description
        elif field == "category":
            product.category = item.category
        product.save()
        if field == "sizes":
            set_product_sizes(product, parse_size_list(item.sizes) or DEFAULT_SIZES)
    if product.is_active:
        # Replace the channel post rather than stacking a second one.
        delete_product_channel_posts(product)
        _queue_channel_post(product)
