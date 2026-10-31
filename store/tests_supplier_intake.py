"""Supplier channel intake: scraper, pricing, Gemini analysis shaping, and the
admin bot review flow from layout choice to a published (and unpublished)
product. Telegram and Gemini are faked; nothing leaves the process.
"""
import json
import os
import tempfile
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from store.models import (
    BackgroundTask,
    Category,
    Product,
    SupplierChannel,
    SupplierItem,
    SupplierItemUpload,
    SupplierPost,
    TelegramBotAdmin,
    TelegramBotMessage,
)
from store.services import admin_bot, supplier_intake as intake, supplier_scraper
from store.services.supplier_ai import normalize_analysis
from store import telegram_notify

OWNER_ID = 111
HELPER_ID = 222
STRANGER_ID = 333


def _image_bytes(fmt="PNG"):
    buffer = BytesIO()
    Image.new("RGB", (4, 4), (120, 40, 40)).save(buffer, format=fmt)
    return buffer.getvalue()


PNG = _image_bytes()


def _entry(colour, photos, *, price="870", garment="g1", title="Square-Neck Tee", slug="tops", sizes=("S", "M")):
    return {
        "garment": garment,
        "colour": colour,
        "photos": list(photos),
        "supplier_price": price,
        "sizes": list(sizes),
        "title": title,
        "product_type": "t-shirt",
        "short_description": "A soft, double-lined tee with a square neckline.",
        "detail_description": "Cut close to the body.",
        "material": "Cotton",
        "fit_notes": "",
        "care_notes": "",
        "seo_title": "",
        "seo_description": "",
        "image_alt_text": "",
        "collection": {"matched_slug": slug, "proposed_new_title": None, "confidence": "high"},
    }


def _preview_html(messages):
    """A minimal t.me/s page: (id, iso datetime, caption, [photo urls])."""
    parts = []
    for message_id, posted, caption, photos in messages:
        photo_html = "".join(
            f'<a class="tgme_widget_message_photo_wrap blured" style="width:500px;background-image:url(\'{url}\')"></a>'
            for url in photos
        )
        parts.append(
            f'<div class="tgme_widget_message_wrap js-widget_message_wrap">'
            f'<div class="tgme_widget_message" data-post="sup/{message_id}">{photo_html}'
            f'<div class="tgme_widget_message_text js-message_text" dir="auto">{caption}</div>'
            f'<time datetime="{posted}" class="time">x</time></div></div>'
        )
    return "<html>" + "".join(parts) + "</html>"


class FakeBot:
    """Stands in for admin_bot_api: records calls, returns plausible results."""

    def __init__(self):
        self.calls = []
        self.next_id = 1000

    def _message(self, photo=False):
        self.next_id += 1
        message = {"message_id": self.next_id}
        if photo:
            message["photo"] = [{"file_id": f"small-{self.next_id}"}, {"file_id": f"file-{self.next_id}"}]
        return message

    def __call__(self, method, payload, files=None):
        self.calls.append((method, payload, files))
        if method == "sendMediaGroup":
            return [self._message(photo=True) for _ in payload["media"]]
        if method == "sendPhoto":
            return self._message(photo=True)
        if method == "sendMessage":
            return self._message()
        return True

    def sent(self, method="sendMessage", chat_id=None):
        return [
            payload for name, payload, _ in self.calls
            if name == method and (chat_id is None or payload.get("chat_id") == chat_id)
        ]


class PricingTests(TestCase):
    def test_formula_matches_agreed_examples(self):
        channel = SupplierChannel(delivery_cover=500, markup_percent=25, min_profit=300, round_to=100)
        cases = {"835": "1700", "1000": "1800", "1600": "2500", "2600": "3800", "5500": "7400"}
        for supplier, retail in cases.items():
            self.assertEqual(intake.retail_price(Decimal(supplier), channel), Decimal(retail), supplier)

    def test_missing_supplier_price_has_no_retail_price(self):
        self.assertIsNone(intake.retail_price(None, SupplierChannel()))

    def test_parse_price_accepts_typed_amounts(self):
        self.assertEqual(intake.parse_price("1,800 birr"), Decimal("1800"))
        with self.assertRaises(intake.IntakeError):
            intake.parse_price("free")


class ScraperTests(TestCase):
    def test_parses_captions_photos_and_skips_nothing(self):
        page = _preview_html([
            (11, "2026-10-26T12:00:00+00:00", "Red tee<br/>Price 870", ["https://cdn/a.jpg", "https://cdn/b.jpg"]),
            (12, "2026-10-26T13:00:00+00:00", "We are hiring", []),
        ])
        messages = supplier_scraper.parse_preview_page(page)
        self.assertEqual([m.message_id for m in messages], [11, 12])
        self.assertEqual(messages[0].caption, "Red tee\nPrice 870")
        self.assertEqual(messages[0].photo_urls, ["https://cdn/a.jpg", "https://cdn/b.jpg"])

    def test_split_colour_posts_merge_but_text_posts_and_late_reposts_do_not(self):
        base = datetime(2026, 10, 16, 15, 0, tzinfo=dt_timezone.utc)
        messages = [
            supplier_scraper.ChannelMessage(1, base, "Linen set 10,500", ["u1"]),
            supplier_scraper.ChannelMessage(2, base + timedelta(minutes=2), "Linen set 10,500", ["u2"]),
            supplier_scraper.ChannelMessage(3, base + timedelta(minutes=3), "Hiring!", []),
            supplier_scraper.ChannelMessage(4, base + timedelta(days=3), "Linen set 10,500", ["u3"]),
        ]
        listings = supplier_scraper.group_listings(messages)
        self.assertEqual([listing.message_ids for listing in listings], [[1, 2], [4]])
        self.assertEqual(listings[0].photo_urls, ["u1", "u2"])

    def test_paging_stops_at_last_seen_post(self):
        pages = {
            None: _preview_html([(30, "2026-10-20T10:00:00+00:00", "c", ["u"]), (31, "2026-10-21T10:00:00+00:00", "d", ["u"])]),
            30: _preview_html([(28, "2026-10-19T10:00:00+00:00", "b", ["u"]), (29, "2026-10-19T11:00:00+00:00", "b2", ["u"])]),
        }
        requested = []

        def fetch(username, before=None):
            requested.append(before)
            return pages.get(before, "")

        messages = supplier_scraper.fetch_new_messages(
            "sup", after_id=28, since=datetime(2026, 10, 1, tzinfo=dt_timezone.utc), fetch=fetch, sleep=lambda s: None
        )
        self.assertEqual([m.message_id for m in messages], [29, 30, 31])
        self.assertEqual(requested, [None, 30])


class AnalysisShapingTests(TestCase):
    def test_bad_indexes_prices_and_dashes_are_cleaned(self):
        raw = {
            "is_product_post": True,
            "layout_guess": "colours",
            "items": [{**_entry("Red", [0, 7, "x"], price="1,600"), "title": "Wide Leg Jorts — Pink"}],
        }
        analysis = normalize_analysis(raw, photo_count=2)
        item = analysis["items"][0]
        self.assertEqual(item["photos"], [0])
        self.assertEqual(item["supplier_price"], "1600")
        self.assertEqual(item["title"], "Wide Leg Jorts, Pink")
        # One item can only be a single product, whatever Gemini guessed.
        self.assertEqual(analysis["layout_guess"], "single")

    def test_no_items_means_not_a_product_post(self):
        analysis = normalize_analysis({"is_product_post": True, "items": []}, photo_count=1)
        self.assertFalse(analysis["is_product_post"])


@override_settings(
    MEDIA_ROOT=tempfile.gettempdir(),
    DEFAULT_FILE_STORAGE="django.core.files.storage.FileSystemStorage",
    SUPPLIER_PICTURE_SETTLE_SECONDS=0,
)
class AdminBotFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.env = patch.dict(os.environ, {"TELEGRAM_OWNER_USER_ID": str(OWNER_ID)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.bot = FakeBot()
        for target, value in (
            ("store.services.admin_bot.admin_bot_api", self.bot),
            ("store.services.admin_bot._admin_bot_settings", lambda: ("token", None)),
            ("store.services.admin_bot.admin_bot_download_file", lambda file_id, **kw: PNG),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.tops = Category.objects.create(
            title="Tops", slug="tops", description="Tops", is_active=True, is_featured=False
        )
        # The seed migration already created the real channels; use our own.
        self.channel = SupplierChannel.objects.create(
            username="test_wear", title="Test wear", sku_prefix="ADT", scrape_since=date(2026, 10, 1)
        )
        self.message_seq = 5000

    # ── helpers ──
    def _send_post(self, entries, layout_guess="colours", photo_count=2):
        post = SupplierPost.objects.create(
            channel=self.channel,
            message_id=3042,
            message_ids=[3042],
            posted_at=timezone.now() - timedelta(hours=3),
            caption="Baby pink and brown tees. Price 870",
            photo_urls=[f"https://cdn.example/{i}.jpg" for i in range(photo_count)],
        )
        analysis = normalize_analysis(
            {"is_product_post": True, "layout_guess": layout_guess, "items": entries}, photo_count
        )
        photos = [(PNG, "image/png")] * photo_count
        with patch.object(intake, "download_post_photos", return_value=photos), patch.object(
            intake, "analyze_post", return_value=analysis
        ):
            self.assertEqual(intake.send_reviews(), 1)
        post.refresh_from_db()
        return post

    def _update(self, payload):
        admin_bot.handle_update(payload)

    def _callback(self, data, user_id=OWNER_ID):
        self._update({
            "callback_query": {
                "id": "cb",
                "data": data,
                "from": {"id": user_id, "first_name": "Ow" if user_id == OWNER_ID else "Abebe"},
                "message": {"message_id": 1, "chat": {"id": user_id, "type": "private"}},
            }
        })

    def _message(self, user_id=OWNER_ID, **fields):
        self.message_seq += 1
        self._update({
            "message": {
                "message_id": self.message_seq,
                "chat": {"id": user_id, "type": "private"},
                "from": {"id": user_id, "first_name": "Ow" if user_id == OWNER_ID else "Abebe"},
                **fields,
            }
        })

    def _picture(self, file_unique_id, user_id=OWNER_ID, as_document=True):
        if as_document:
            self._message(user_id, document={"file_id": f"f-{file_unique_id}", "file_unique_id": file_unique_id, "mime_type": "image/webp"})
        else:
            self._message(user_id, photo=[{"file_id": f"f-{file_unique_id}", "file_unique_id": file_unique_id}])

    def _toasts(self):
        return [payload.get("text") for name, payload, _ in self.bot.calls if name == "answerCallbackQuery"]

    # ── review delivery ──
    def test_review_sends_photos_then_summary_and_keeps_file_ids(self):
        post = self._send_post([_entry("Baby pink", [0]), _entry("Brown", [1])])

        self.assertEqual(post.status, SupplierPost.STATUS_SENT)
        self.assertEqual(len(self.bot.sent("sendMediaGroup", OWNER_ID)), 1)
        summary = self.bot.sent("sendMessage", OWNER_ID)[0]
        self.assertIn("Supplier 870", summary["text"])
        self.assertIn("1,700 ETB", summary["text"])
        buttons = [b["text"] for row in summary["reply_markup"]["inline_keyboard"] for b in row]
        self.assertIn("✓ Colour variants", buttons)
        self.assertTrue(all(photo.telegram_file_id for photo in post.photos.all()))
        self.assertEqual(TelegramBotMessage.objects.filter(post=post, kind=TelegramBotMessage.KIND_POST_PHOTO).count(), 2)

    def test_daily_limit_counts_reviews_already_sent_today(self):
        self._send_post([_entry("Red", [0])], layout_guess="single", photo_count=1)
        SupplierPost.objects.create(
            channel=self.channel, message_id=4000, posted_at=timezone.now(), caption="x", photo_urls=["u"]
        )
        with patch.object(intake, "analyze_and_send") as analyze_and_send:
            self.assertEqual(intake.send_reviews(limit=1), 0)
        analyze_and_send.assert_not_called()

    # ── access control ──
    def test_strangers_request_access_and_owner_approves(self):
        self._message(STRANGER_ID, text="/start")
        request = self.bot.sent(chat_id=OWNER_ID)[-1]
        self.assertIn("wants to use the admin bot", request["text"])
        self.assertEqual(TelegramBotAdmin.objects.get(telegram_user_id=STRANGER_ID).status, TelegramBotAdmin.STATUS_PENDING)

        self._callback(f"A:ok:{STRANGER_ID}")
        self.assertEqual(TelegramBotAdmin.objects.get(telegram_user_id=STRANGER_ID).status, TelegramBotAdmin.STATUS_APPROVED)
        self.assertIn("You're in", self.bot.sent(chat_id=STRANGER_ID)[-1]["text"])

    def test_non_admins_cannot_press_buttons_or_approve(self):
        post = self._send_post([_entry("Red", [0])], layout_guess="single", photo_count=1)
        self._callback(f"L:{post.pk}:single", user_id=STRANGER_ID)
        self.assertEqual(SupplierPost.objects.get(pk=post.pk).status, SupplierPost.STATUS_SENT)

        TelegramBotAdmin.objects.create(telegram_user_id=HELPER_ID, status=TelegramBotAdmin.STATUS_APPROVED)
        TelegramBotAdmin.objects.create(telegram_user_id=STRANGER_ID, status=TelegramBotAdmin.STATUS_PENDING)
        self._callback(f"A:ok:{STRANGER_ID}", user_id=HELPER_ID)
        self.assertEqual(TelegramBotAdmin.objects.get(telegram_user_id=STRANGER_ID).status, TelegramBotAdmin.STATUS_PENDING)
        self.assertIn("Only the owner can approve admins.", self._toasts())

    def test_owner_cannot_be_removed(self):
        self._callback(f"AR:{OWNER_ID}")
        self.assertEqual(TelegramBotAdmin.objects.get(telegram_user_id=OWNER_ID).status, TelegramBotAdmin.STATUS_APPROVED)

    # ── layout -> cards -> pictures -> publish ──
    def test_single_layout_then_pictures_publishes_live_product(self):
        post = self._send_post([_entry("Baby pink", [0]), _entry("Brown", [1])])
        self._callback(f"L:{post.pk}:single")

        item = SupplierItem.objects.get(post=post)
        self.assertEqual(item.price, Decimal("1700"))
        self.assertEqual(item.category, self.tops)
        self.assertEqual(item.photo_positions, [0, 1])
        card = self.bot.sent(chat_id=OWNER_ID)[-1]
        self.assertIn("Gemini prompts", card["text"])
        self.assertIn("ghost mannequin", card["text"])

        self._callback(f"P:{item.pk}")
        self._picture("cover-1")

        item.refresh_from_db()
        product = item.product
        self.assertEqual(item.status, SupplierItem.STATUS_PUBLISHED)
        self.assertTrue(product.is_active)
        self.assertEqual(product.sku, "ADT-3042")
        self.assertEqual(product.price, Decimal("1700"))
        self.assertEqual(product.available_sizes, "S,M")
        self.assertTrue(product.product_image.name.endswith(".png"))
        self.assertTrue(
            BackgroundTask.objects.filter(
                task_type=BackgroundTask.TYPE_TELEGRAM_PRODUCT_POST, payload__product_id=product.id
            ).exists()
        )
        self.assertEqual(SupplierPost.objects.get(pk=post.pk).status, SupplierPost.STATUS_DONE)

    def test_late_album_pictures_join_the_gallery_and_retries_are_ignored(self):
        post = self._send_post([_entry("Red", [0])], layout_guess="single", photo_count=1)
        self._callback(f"L:{post.pk}:single")
        item = SupplierItem.objects.get(post=post)
        self._callback(f"P:{item.pk}")

        self._picture("one")
        self._picture("two")
        self._picture("two")  # Telegram redelivering the same update.

        item.refresh_from_db()
        self.assertEqual(item.product.p_images.count(), 1)
        self.assertEqual(SupplierItemUpload.objects.filter(item=item).count(), 2)

    def test_colour_variants_publish_as_linked_siblings(self):
        post = self._send_post([_entry("Baby pink", [0]), _entry("Brown", [1])])
        self._callback(f"L:{post.pk}:colours")
        pink, brown = SupplierItem.objects.filter(post=post).order_by("position")

        for item, upload in ((pink, "pink"), (brown, "brown")):
            self._callback(f"P:{item.pk}")
            self._picture(upload)

        pink.refresh_from_db()
        brown.refresh_from_db()
        self.assertEqual((pink.product.sku, brown.product.sku), ("ADT-3042-1", "ADT-3042-2"))
        self.assertIsNotNone(pink.product.color_group_id)
        self.assertEqual(pink.product.color_group_id, brown.product.color_group_id)

    def test_claimed_item_blocks_other_admins(self):
        TelegramBotAdmin.objects.create(telegram_user_id=HELPER_ID, full_name="Abebe", status=TelegramBotAdmin.STATUS_APPROVED)
        post = self._send_post([_entry("Red", [0])], layout_guess="single", photo_count=1)
        self._callback(f"L:{post.pk}:single")
        item = SupplierItem.objects.get(post=post)

        self._callback(f"P:{item.pk}", user_id=HELPER_ID)
        self._callback(f"P:{item.pk}")
        self.assertIn("Abebe is already adding pictures for this one.", self._toasts())

    def test_missing_collection_holds_pictures_until_set(self):
        post = self._send_post([_entry("Red", [0], slug="no-such-collection")], layout_guess="single", photo_count=1)
        self._callback(f"L:{post.pk}:single")
        item = SupplierItem.objects.get(post=post)
        self.assertIsNone(item.category)

        self._callback(f"P:{item.pk}")
        self._picture("held")
        item.refresh_from_db()
        self.assertIsNone(item.product)
        self.assertIn("Set the collection", self.bot.sent(chat_id=OWNER_ID)[-1]["text"])

        self._callback(f"ECS:{item.pk}:{self.tops.pk}")
        item.refresh_from_db()
        self.assertEqual(item.status, SupplierItem.STATUS_PUBLISHED)
        self.assertEqual(item.product.category, self.tops)

    def test_price_edit_updates_the_live_product(self):
        post = self._send_post([_entry("Red", [0])], layout_guess="single", photo_count=1)
        self._callback(f"L:{post.pk}:single")
        item = SupplierItem.objects.get(post=post)
        self._callback(f"P:{item.pk}")
        self._picture("cover")

        self._callback(f"EF:{item.pk}:price")
        self._message(text="abc")
        self.assertIn("Send the price as a number", self.bot.sent(chat_id=OWNER_ID)[-1]["text"])
        self._message(text="1,950")

        item.refresh_from_db()
        self.assertEqual(item.price, Decimal("1950"))
        self.assertEqual(Product.objects.get(pk=item.product_id).price, Decimal("1950"))

    def test_unpublish_hides_product_and_deletes_channel_posts(self):
        post = self._send_post([_entry("Red", [0])], layout_guess="single", photo_count=1)
        self._callback(f"L:{post.pk}:single")
        item = SupplierItem.objects.get(post=post)
        self._callback(f"P:{item.pk}")
        self._picture("cover")
        Product.objects.filter(pk=item.product_id).update(telegram_channel_message_ids=[77, 78])

        with patch("store.services.supplier_intake.delete_product_channel_posts", return_value=True) as delete_posts:
            self._callback(f"U:{item.pk}")
        delete_posts.assert_called_once()
        item.refresh_from_db()
        self.assertEqual(item.status, SupplierItem.STATUS_UNPUBLISHED)
        self.assertFalse(item.product.is_active)

        self._callback(f"R:{item.pk}")
        item.refresh_from_db()
        self.assertTrue(item.product.is_active)

    def test_pictures_without_a_card_are_refused(self):
        self._picture("orphan")
        self.assertIn("Add pictures", self.bot.sent(chat_id=OWNER_ID)[-1]["text"])
        self.assertFalse(SupplierItemUpload.objects.exists())

    def test_skipping_last_item_closes_the_post(self):
        post = self._send_post([_entry("Red", [0])], layout_guess="single", photo_count=1)
        self._callback(f"L:{post.pk}:single")
        item = SupplierItem.objects.get(post=post)
        self._callback(f"S:{item.pk}")
        self.assertEqual(SupplierPost.objects.get(pk=post.pk).status, SupplierPost.STATUS_DONE)

    def test_stale_reviews_expire(self):
        post = self._send_post([_entry("Red", [0])], layout_guess="single", photo_count=1)
        SupplierPost.objects.filter(pk=post.pk).update(sent_at=timezone.now() - timedelta(days=11))
        self.assertEqual(intake.expire_stale(), 1)
        self.assertEqual(SupplierPost.objects.get(pk=post.pk).status, SupplierPost.STATUS_EXPIRED)


class IngestTests(TestCase):
    def setUp(self):
        self.channel = SupplierChannel.objects.create(
            username="sup", title="Sup", sku_prefix="SUP", scrape_since=date(2026, 10, 1)
        )

        # Photo URLs name the picture they serve, so a repost reuses its URL's image.
        pictures = {
            "red": self._picture("left"),
            "green": self._picture("right"),
            "blue": self._picture("top"),
        }
        patcher = patch.object(
            supplier_scraper, "download", side_effect=lambda url, **kw: pictures[url.rsplit("/", 1)[-1]]
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _picture(bright_side):
        """Distinct, deterministic photos: a bright half on one side."""
        image = Image.new("L", (64, 64), 20)
        box = {"left": (0, 0, 32, 64), "right": (32, 0, 64, 64), "top": (0, 0, 64, 32)}[bright_side]
        image.paste(230, box)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    def _ingest(self, messages):
        page = _preview_html(messages)
        return intake.ingest_channel(
            self.channel, fetch=lambda username, before=None: page if before is None else "", sleep=lambda s: None
        )

    def test_ingest_stores_listings_from_the_start_date(self):
        created = self._ingest([
            (10, "2026-09-20T10:00:00+00:00", "Too old", ["https://cdn/red"]),
            (11, "2026-10-26T10:00:00+00:00", "Red tee 870", ["https://cdn/red"]),
            (12, "2026-10-27T10:00:00+00:00", "Hiring", []),
        ])
        self.assertEqual(created, 1)
        post = SupplierPost.objects.get()
        self.assertEqual(post.message_id, 11)
        self.assertTrue(post.photo_hash)
        self.assertIsNone(post.posted_at.tzinfo)  # USE_TZ is off: stored as naive local time.
        self.channel.refresh_from_db()
        self.assertEqual(self.channel.last_message_id, 12)

    def test_reposted_photo_bumps_waiting_post_and_shared_caption_does_not_merge(self):
        self._ingest([
            (11, "2026-10-21T10:00:00+00:00", "Red tank 835", ["https://cdn/red"]),
            (12, "2026-10-21T15:00:00+00:00", "New Design Top 5,000", ["https://cdn/green"]),
            (13, "2026-10-22T15:00:00+00:00", "New Design Top 5,000", ["https://cdn/blue"]),
            (14, "2026-10-26T10:00:00+00:00", "Restock! Red tank 835", ["https://cdn/red"]),
        ])
        self.assertEqual(SupplierPost.objects.count(), 3)
        red = SupplierPost.objects.get(photo_urls=["https://cdn/red"])
        self.assertEqual((red.message_id, red.message_ids), (14, [11, 14]))
        self.assertEqual(red.posted_at.day, 26)

    def test_reposts_of_handled_posts_are_ignored_until_skipped(self):
        self._ingest([(11, "2026-10-21T10:00:00+00:00", "Red tank", ["https://cdn/red"])])
        intake.mark_on_site("sup", 11, "adot290")
        self.assertEqual(SupplierPost.objects.get().status, SupplierPost.STATUS_ON_SITE)

        self._ingest([(20, "2026-10-30T10:00:00+00:00", "Red tank again", ["https://cdn/red"])])
        self.assertEqual(SupplierPost.objects.count(), 1)

        SupplierPost.objects.update(status=SupplierPost.STATUS_SKIPPED)
        self._ingest([(21, "2026-10-31T10:00:00+00:00", "Red tank back", ["https://cdn/red"])])
        self.assertEqual(SupplierPost.objects.count(), 2)


class ChannelPostTrackingTests(TestCase):
    def test_channel_post_ids_are_recorded_and_deleted(self):
        from store.tests import _make_catalog

        _, _, product = _make_catalog("Track")
        env = {
            "TELEGRAM_CUSTOMER_BOT_TOKEN": "t",
            "TELEGRAM_CUSTOMER_CHANNEL_CHAT_ID": "@chan",
            "TELEGRAM_CUSTOMER_BOT_USERNAME": "bot",
        }
        with patch.dict(os.environ, env), patch.object(
            telegram_notify, "_send_media_entry_photo", return_value={"message_id": 91}
        ), patch.object(telegram_notify, "_collect_product_media_entries", return_value=[{"field_file": None}]):
            self.assertTrue(telegram_notify.post_product_to_channel(product, force=True))
        product.refresh_from_db()
        self.assertEqual(product.telegram_channel_message_ids, [91])

        with patch.dict(os.environ, env), patch.object(
            telegram_notify, "_telegram_api_request", return_value=True
        ) as api:
            self.assertTrue(telegram_notify.delete_product_channel_posts(product))
        self.assertEqual(api.call_args.args[0], "deleteMessages")
        self.assertEqual(json.loads(api.call_args.args[1]["message_ids"]), [91])
        product.refresh_from_db()
        self.assertEqual(product.telegram_channel_message_ids, [])


class AdminWebhookTests(TestCase):
    def test_failures_still_return_200_so_telegram_does_not_redeliver(self):
        with patch.dict(os.environ, {"TELEGRAM_ADMIN_WEBHOOK_SECRET": "s3cret"}), patch(
            "store.services.admin_bot.handle_update", side_effect=RuntimeError("boom")
        ):
            response = self.client.post(
                "/telegram/admin-webhook/",
                data=json.dumps({"message": {}}),
                content_type="application/json",
                HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="s3cret",
            )
        self.assertEqual(response.status_code, 200)

    def test_wrong_secret_is_rejected(self):
        with patch.dict(os.environ, {"TELEGRAM_ADMIN_WEBHOOK_SECRET": "s3cret"}):
            response = self.client.post(
                "/telegram/admin-webhook/", data="{}", content_type="application/json",
                HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="nope",
            )
        self.assertEqual(response.status_code, 403)
