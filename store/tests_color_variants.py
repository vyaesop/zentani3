"""Colour variants: one garment, several colours, one product per colour.

Covers the service layer (clone / link / unlink / sync), the storefront
swatches and card counts, the Telegram caption, the merchant feed grouping,
and the dashboard "Add a colour" flow and Colours panel actions.
"""
import tempfile
from decimal import Decimal
from io import BytesIO

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from store.models import BackgroundTask, Product, ProductColorGroup
from store.services import color_variants
from store.services.inventory import set_product_sizes
from store.telegram_notify import _product_caption, _product_post_signature
from store.tests import _make_catalog

def _png_bytes():
    """A real 1x1 PNG so ImageField validation passes in form posts."""
    buffer = BytesIO()
    Image.new("RGB", (1, 1), (17, 17, 17)).save(buffer, format="PNG")
    return buffer.getvalue()


PNG_BYTES = _png_bytes()


def _png(name="cover.png"):
    return SimpleUploadedFile(name, PNG_BYTES, content_type="image/png")


def _make_black(prefix="Colour"):
    category, brand, product = _make_catalog(prefix)
    product.title = f"Black {prefix} Shirt"
    product.color = "Black"
    product.short_description = "Soft cotton, boxy fit."
    product.material = "Cotton"
    product.save()
    # The live fixture product queues its own Telegram post on save; tests
    # below assert that the colour tools add none of their own.
    BackgroundTask.objects.all().delete()
    return category, brand, product


@override_settings(MEDIA_ROOT=tempfile.gettempdir(), DEFAULT_FILE_STORAGE="django.core.files.storage.FileSystemStorage")
class ColorVariantServiceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.category, self.brand, self.black = _make_black("Svc")

    def test_create_variant_copies_details_groups_and_stays_hidden(self):
        blue = color_variants.create_color_variant(self.black, color="Blue", cover_image=_png())
        self.black.refresh_from_db()

        self.assertIsNotNone(self.black.color_group_id)
        self.assertEqual(blue.color_group_id, self.black.color_group_id)
        self.assertEqual(blue.title, "Blue Svc Shirt")
        self.assertEqual(blue.color, "Blue")
        self.assertEqual(blue.sku, "SKU-SVC-1-BLUE")
        self.assertEqual(blue.short_description, self.black.short_description)
        self.assertEqual(blue.material, "Cotton")
        self.assertEqual(blue.category_id, self.category.id)
        self.assertEqual(blue.brand_id, self.brand.id)
        self.assertEqual(blue.price, self.black.price)
        self.assertFalse(blue.is_active)
        self.assertNotEqual(blue.slug, self.black.slug)
        self.assertEqual(blue.available_sizes, "S,M,L")
        self.assertGreater(blue.stock_quantity, 0)
        # Nothing was queued for Telegram: publishing stays explicit.
        self.assertFalse(BackgroundTask.objects.filter(task_type=BackgroundTask.TYPE_TELEGRAM_PRODUCT_POST).exists())

    def test_suggestions_never_stack_colour_tokens_or_collide(self):
        blue = color_variants.create_color_variant(self.black, color="Blue", cover_image=_png())
        # Cloning the clone: SKU derives from the base, not BLUE-RED.
        self.assertEqual(color_variants.suggest_variant_sku(blue, "Red"), "SKU-SVC-1-RED")
        self.assertEqual(color_variants.suggest_variant_title(blue, "Red"), "Red Svc Shirt")
        # A title without the colour word is kept.
        self.black.title = "Svc Shirt"
        self.assertEqual(color_variants.suggest_variant_title(self.black, "Red"), "Svc Shirt")
        # Slugs stay unique even when titles repeat.
        red = color_variants.create_color_variant(self.black, color="Red", cover_image=_png(), title="Blue Svc Shirt")
        self.assertNotEqual(red.slug, blue.slug)

    def test_duplicate_sku_is_rejected(self):
        with self.assertRaises(ValueError):
            color_variants.create_color_variant(self.black, color="Blue", cover_image=_png(), sku=self.black.sku)

    def test_unlink_dissolves_a_group_left_with_one_member(self):
        blue = color_variants.create_color_variant(self.black, color="Blue", cover_image=_png())
        group_id = blue.color_group_id
        color_variants.unlink_product(blue)
        self.black.refresh_from_db()
        self.assertIsNone(self.black.color_group_id)
        self.assertFalse(ProductColorGroup.objects.filter(pk=group_id).exists())

    def test_link_merges_two_families(self):
        blue = color_variants.create_color_variant(self.black, color="Blue", cover_image=_png())
        _, _, other = _make_black("Other")
        green = color_variants.create_color_variant(other, color="Green", cover_image=_png())
        old_group_id = other.color_group_id

        color_variants.link_products(self.black, other)

        for product in (self.black, blue, other, green):
            product.refresh_from_db()
            self.assertEqual(product.color_group_id, self.black.color_group_id)
        self.assertFalse(ProductColorGroup.objects.filter(pk=old_group_id).exists())

    def test_sync_copies_shared_fields_only_and_never_posts(self):
        blue = color_variants.create_color_variant(self.black, color="Blue", cover_image=_png(), is_active=True)
        self.black.detail_description = "New long copy"
        self.black.price = Decimal("250.00")
        self.black.save()
        BackgroundTask.objects.all().delete()

        updated = color_variants.sync_shared_details(self.black)
        blue.refresh_from_db()

        self.assertEqual(updated, 1)
        self.assertEqual(blue.detail_description, "New long copy")
        self.assertEqual(blue.price, Decimal("100.00"))  # price is opt-in
        self.assertEqual(blue.color, "Blue")
        self.assertEqual(blue.title, "Blue Svc Shirt")
        self.assertFalse(BackgroundTask.objects.filter(task_type=BackgroundTask.TYPE_TELEGRAM_PRODUCT_POST).exists())

        color_variants.sync_shared_details(self.black, include_price=True)
        blue.refresh_from_db()
        self.assertEqual(blue.price, Decimal("250.00"))


@override_settings(MEDIA_ROOT=tempfile.gettempdir(), DEFAULT_FILE_STORAGE="django.core.files.storage.FileSystemStorage")
class ColorVariantStorefrontTests(TestCase):
    def setUp(self):
        cache.clear()
        self.category, self.brand, self.black = _make_black("Shop")
        self.blue = color_variants.create_color_variant(self.black, color="Blue", cover_image=_png(), is_active=True)
        self.hidden = color_variants.create_color_variant(self.black, color="Grey", cover_image=_png())

    def test_detail_shows_live_siblings_as_swatches_and_links_to_their_pages(self):
        response = self.client.get(reverse("store:product-detail", args=[self.black.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="zh-swatch is-current"')
        self.assertContains(response, reverse("store:product-detail", args=[self.blue.slug]))
        self.assertContains(response, ">Blue<")
        self.assertNotContains(response, ">Grey<")  # hidden colours never leak

        # And the blue page links back to black.
        response = self.client.get(reverse("store:product-detail", args=[self.blue.slug]))
        self.assertContains(response, reverse("store:product-detail", args=[self.black.slug]))

    def test_ungrouped_product_has_no_swatch_row(self):
        _, _, lone = _make_catalog("Lone")
        response = self.client.get(reverse("store:product-detail", args=[lone.slug]))
        self.assertNotContains(response, "zh-pdp__colours")

    def test_family_with_one_live_colour_hides_the_row(self):
        self.blue.is_active = False
        self.blue.save()
        response = self.client.get(reverse("store:product-detail", args=[self.black.slug]))
        self.assertNotContains(response, "zh-pdp__colours")

    def test_collection_cards_show_colour_count(self):
        response = self.client.get(reverse("store:all-products"))
        body = response.content.decode()
        start = body.find("zh-module__body")
        self.assertContains(response, "2 colours", msg_prefix=body[start : start + 900])

    def test_merchant_feed_groups_colours_together(self):
        response = self.client.get(reverse("store:merchant-feed"))
        body = response.content.decode()
        self.assertIn(f"colour-group-{self.black.color_group_id}", body)
        self.assertEqual(body.count(f"<g:item_group_id>colour-group-{self.black.color_group_id}</g:item_group_id>"), 6)


@override_settings(
    MEDIA_ROOT=tempfile.gettempdir(),
    DEFAULT_FILE_STORAGE="django.core.files.storage.FileSystemStorage",
    SITE_URL="https://shop.example.et",
)
class ColorVariantTelegramTests(TestCase):
    def setUp(self):
        cache.clear()
        _, _, self.black = _make_black("Tg")
        self.blue = color_variants.create_color_variant(self.black, color="Blue", cover_image=_png(), is_active=True)
        self.black.refresh_from_db()

    def test_caption_names_the_colour_and_links_the_others(self):
        caption = _product_caption(self.black)
        self.assertIn("<b>Colour</b>: Black", caption)
        self.assertIn("<b>Also in</b>:", caption)
        self.assertIn(f"https://shop.example.et/product/{self.blue.slug}/", caption)
        self.assertIn(">Blue</a>", caption)

    def test_hidden_siblings_are_not_advertised(self):
        self.blue.is_active = False
        self.blue.save()
        caption = _product_caption(self.black)
        self.assertNotIn("Also in", caption)

    def test_signature_changes_when_colour_changes(self):
        before = _product_post_signature(self.black)
        self.black.color = "Jet Black"
        self.assertNotEqual(before, _product_post_signature(self.black))


@override_settings(MEDIA_ROOT=tempfile.gettempdir(), DEFAULT_FILE_STORAGE="django.core.files.storage.FileSystemStorage")
class ColorVariantDashboardTests(TestCase):
    def setUp(self):
        cache.clear()
        self.category, self.brand, self.black = _make_black("Dash")
        self.staff = User.objects.create_user(username="0911700000", password="test-pass-123", is_staff=True)
        self.client.login(username="0911700000", password="test-pass-123")

    def _post_colour(self, **overrides):
        data = {
            "color": "Blue",
            "title": "Black Dash Shirt",
            "sku": "SKU-DASH-1-BLUE",
            "price": "100.00",
            "available_sizes": "S, M, L",
        }
        data.update(overrides)
        files = {"product_image": _png(), "gallery_images": [_png("g1.png"), _png("g2.png")]}
        return self.client.post(
            reverse("store:dashboard-product-add-color", args=[self.black.id]),
            {**data, **files},
        )

    def test_add_colour_page_is_prefilled_from_the_source(self):
        response = self.client.get(reverse("store:dashboard-product-add-color", args=[self.black.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="Black Dash Shirt"')
        self.assertContains(response, 'value="SKU-DASH-1-ALT"')
        self.assertContains(response, 'value="S, M, L"')
        self.assertContains(response, "Create as hidden draft")

    def _assert_created(self, response):
        errors = response.context["form"].errors if response.status_code == 200 and response.context else ""
        self.assertEqual(response.status_code, 302, f"colour form did not save: {errors}")

    def test_posting_a_colour_creates_a_hidden_sibling_with_photos_and_sizes(self):
        response = self._post_colour()
        self._assert_created(response)
        blue = Product.objects.get(sku="SKU-DASH-1-BLUE")
        self.assertRedirects(response, reverse("store:dashboard-product-edit", args=[blue.id]))
        self.assertFalse(blue.is_active)
        self.assertEqual(blue.color, "Blue")
        self.assertEqual(blue.title, "Blue Dash Shirt")  # colour word swapped from the kept title
        self.assertEqual(blue.p_images.count(), 2)
        self.assertEqual(blue.available_sizes, "S,M,L")
        self.black.refresh_from_db()
        self.assertEqual(blue.color_group_id, self.black.color_group_id)
        self.assertFalse(BackgroundTask.objects.filter(task_type=BackgroundTask.TYPE_TELEGRAM_PRODUCT_POST).exists())

    def test_create_and_post_goes_live_and_queues_its_own_telegram_post(self):
        self._assert_created(self._post_colour(save_and_publish="1"))
        blue = Product.objects.get(sku="SKU-DASH-1-BLUE")
        self.assertTrue(blue.is_active)
        tasks = BackgroundTask.objects.filter(task_type=BackgroundTask.TYPE_TELEGRAM_PRODUCT_POST)
        self.assertEqual(tasks.count(), 1)
        self.assertEqual(tasks.first().payload["product_id"], blue.id)

    def test_duplicate_colour_and_sku_are_rejected_with_guidance(self):
        response = self._post_colour(color="black")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists in this colour family")
        response = self._post_colour(sku=self.black.sku)
        self.assertContains(response, "already used by another product")
        self.assertEqual(Product.objects.filter(color_group__isnull=False).count(), 0)

    def test_editor_shows_colours_panel_and_list_shows_family_pill(self):
        blue = color_variants.create_color_variant(self.black, color="Blue", cover_image=_png(), is_active=True)
        response = self.client.get(reverse("store:dashboard-product-edit", args=[self.black.id]))
        self.assertContains(response, "Editing now")
        self.assertContains(response, reverse("store:dashboard-product-edit", args=[blue.id]))
        self.assertContains(response, "Copy details to other colours")

        response = self.client.get(reverse("store:dashboard-products"))
        self.assertContains(response, "2 colours")
        response = self.client.get(reverse("store:dashboard-products") + f"?group={self.black.color_group_id}")
        self.assertContains(response, "Colours of")
        self.assertContains(response, blue.title)

    def test_link_unlink_and_sync_actions(self):
        _, _, other = _make_black("Loose")
        url = reverse("store:dashboard-product-colors", args=[self.black.id])

        self.client.post(url, {"action": "link", "other_product_id": other.id})
        self.black.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(other.color_group_id, self.black.color_group_id)

        self.black.detail_description = "Shared copy"
        self.black.save()
        self.client.post(url, {"action": "sync_details"})
        other.refresh_from_db()
        self.assertEqual(other.detail_description, "Shared copy")
        self.assertEqual(other.title, "Black Loose Shirt")

        self.client.post(url, {"action": "unlink", "other_product_id": other.id})
        other.refresh_from_db()
        self.black.refresh_from_db()
        self.assertIsNone(other.color_group_id)
        self.assertIsNone(self.black.color_group_id)

    def test_non_staff_cannot_reach_colour_tools(self):
        self.client.logout()
        User.objects.create_user(username="0911710000", password="test-pass-123")
        self.client.login(username="0911710000", password="test-pass-123")
        response = self.client.get(reverse("store:dashboard-product-add-color", args=[self.black.id]))
        self.assertNotEqual(response.status_code, 200)
