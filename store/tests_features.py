"""Tests for the September 2026 commerce hardening pass.

Covers: hidden-product handling, SEO surfaces (robots, sitemap, feed,
placeholder scrubbing, structured data), the consistent delivery promise,
order groups + confirmation page, cancellation stock restore, phone
normalisation, price formatting, stock messaging, review invites, rate
limiting, CSP, SMS/email notifications, Chapa prepay, search logging,
translations and static asset versioning.
"""
import json
import hashlib
import hmac
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from store import tasks as task_queue
from store.models import (
    Address,
    BackgroundTask,
    Brand,
    Cart,
    Category,
    Order,
    OrderGroup,
    Product,
    ProductReview,
    ProductSizeStock,
    SearchLog,
)
from store.phone import normalize_et_phone, to_e164
from store.seo import clean_seo_copy, has_placeholder
from store.services.checkout import cancel_order_line, delivery_fee_for
from store.services.inventory import set_product_sizes
from store.tests import _make_catalog


def _stock_for(product, size):
    return ProductSizeStock.objects.get(product=product, size=size).quantity


class HiddenProductTests(TestCase):
    def setUp(self):
        cache.clear()
        self.category, self.brand, self.product = _make_catalog("Hidden")
        self.hidden = Product.objects.create(
            title="Hidden Jacket",
            slug="hidden-jacket",
            sku="SKU-HIDDEN-JACKET",
            short_description="Not live",
            product_image="product/test.jpg",
            price=Decimal("900.00"),
            category=self.category,
            brand=self.brand,
            is_active=False,
            is_featured=True,
            is_sold_out=False,
        )
        set_product_sizes(self.hidden, ["M"])

    def test_hidden_product_returns_404_with_alternatives_and_noindex(self):
        response = self.client.get(reverse("store:product-detail", args=[self.hidden.slug]))
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "no longer available", status_code=404)
        self.assertContains(response, 'name="robots" content="noindex', status_code=404)
        # Live alternative from the same collection is offered instead of a dead buy button.
        self.assertContains(response, self.product.title, status_code=404)
        self.assertNotContains(response, "schema.org/InStock", status_code=404)
        self.assertNotContains(response, 'id="add-to-cart-btn"', status_code=404)

    def test_staff_can_preview_hidden_product(self):
        User.objects.create_user(username="0911550000", password="test-pass-123", is_staff=True)
        self.client.login(username="0911550000", password="test-pass-123")
        response = self.client.get(reverse("store:product-detail", args=[self.hidden.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Staff preview")
        self.assertContains(response, 'name="robots" content="noindex')
        self.assertContains(response, "schema.org/OutOfStock")

    def test_hidden_product_not_in_sitemap_or_feed(self):
        sitemap = self.client.get(reverse("store:sitemap"))
        self.assertEqual(sitemap.status_code, 200)
        self.assertContains(sitemap, f"/product/{self.product.slug}/")
        self.assertNotContains(sitemap, f"/product/{self.hidden.slug}/")

        feed = self.client.get(reverse("store:merchant-feed"))
        self.assertEqual(feed.status_code, 200)
        self.assertIn("application/xml", feed["Content-Type"])
        self.assertContains(feed, "<g:id>SKU-HIDDEN-JACKET", count=0)
        self.assertContains(feed, f"<g:id>{self.product.sku}-M</g:id>")
        self.assertContains(feed, "<g:availability>in stock</g:availability>")


class SeoSurfaceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.category, self.brand, self.product = _make_catalog("Seo")

    def test_robots_txt_points_at_sitemap_and_blocks_private_paths(self):
        response = self.client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain")
        body = response.content.decode()
        self.assertIn("Sitemap: http://testserver/sitemap.xml", body)
        self.assertIn("Disallow: /cart/", body)
        self.assertIn("Disallow: /dashboard/", body)
        self.assertIn("Allow: /", body)

    def test_sitemap_lists_pages_products_collections(self):
        response = self.client.get(reverse("store:sitemap"))
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn(f"/product/{self.product.slug}/", body)
        self.assertIn(f"/{self.category.slug}/", body)
        self.assertIn("/delivery-returns/", body)
        self.assertIn("/faq/", body)

    @override_settings(SITE_URL="https://shop.example.et")
    def test_sitemap_uses_configured_site_url(self):
        response = self.client.get(reverse("store:sitemap"))
        self.assertContains(response, "https://shop.example.et/product/")

    def test_every_page_carries_canonical_and_private_pages_noindex(self):
        home = self.client.get(reverse("store:home"))
        self.assertContains(home, '<link rel="canonical" href="http://testserver/">')
        self.assertContains(home, '"@type": "OnlineStore"')
        self.assertContains(home, '"@type": "WebSite"')
        cart = self.client.get(reverse("store:cart"))
        self.assertContains(cart, 'name="robots" content="noindex, nofollow"')
        search = self.client.get(reverse("store:search"), {"q": "ring"})
        self.assertContains(search, 'name="robots" content="noindex, follow"')

    def test_category_page_has_unique_meta_description(self):
        self.category.meta_description = "Rings for every day, delivered in Addis."
        self.category.save()
        response = self.client.get(reverse("store:category-products", args=[self.category.slug]))
        self.assertContains(response, 'content="Rings for every day, delivered in Addis."')

    def test_placeholder_detection_and_cleaning(self):
        self.assertTrue(has_placeholder("Nike Air Force 1 | [Store Name]"))
        self.assertTrue(has_placeholder("Great top from {brand}"))
        self.assertTrue(has_placeholder("Lorem ipsum dolor"))
        self.assertFalse(has_placeholder("Nike Air Force 1 Low '07 - Triple Black"))
        self.assertEqual(clean_seo_copy("Nike Air Force 1 | [Store Name]"), "Nike Air Force 1")
        self.assertEqual(clean_seo_copy("[Your Store Name]", fallback="Zentanee"), "Zentanee")

    def test_leaked_placeholder_title_never_reaches_the_page(self):
        self.product.seo_title = "Seo Ring Sneakers | [Store Name]"
        self.product.seo_description = "Buy at [Your Store Name] today"
        self.product.save()
        response = self.client.get(reverse("store:product-detail", args=[self.product.slug]))
        self.assertNotContains(response, "[Store Name]")
        self.assertNotContains(response, "[Your Store Name]")
        self.assertContains(response, "<title>Seo Ring Sneakers</title>")

    def test_scrub_command_cleans_placeholders(self):
        from io import StringIO

        from django.core.management import call_command

        self.product.seo_title = "Seo Ring | [Store Name]"
        self.product.save()
        out = StringIO()
        call_command("scrub_seo_placeholders", "--apply", stdout=out)
        self.product.refresh_from_db()
        self.assertEqual(self.product.seo_title, "Seo Ring")
        self.assertIn("Cleaned 1 product", out.getvalue())

    def test_dashboard_form_rejects_placeholder_copy(self):
        from store.dashboard_forms import DashboardProductForm

        form = DashboardProductForm(
            data={
                "title": "Fine Dress",
                "slug": "fine-dress",
                "sku": "SKU-FINE",
                "short_description": "Lovely",
                "seo_title": "Fine Dress | [Store Name]",
                "price": "100.00",
                "category": self.category.id,
                "is_active": True,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("seo_title", form.errors)
        self.assertIn("template text", form.errors["seo_title"][0])

    def test_dashboard_form_rejects_zero_price(self):
        from store.dashboard_forms import DashboardProductForm

        form = DashboardProductForm(
            data={"title": "Free", "slug": "free", "sku": "SKU-FREE", "short_description": "x", "price": "0", "category": self.category.id}
        )
        self.assertFalse(form.is_valid())
        self.assertIn("price", form.errors)

    def test_product_schema_carries_shipping_returns_and_rating(self):
        user = User.objects.create_user(username="0911560000", password="test-pass-123")
        ProductReview.objects.create(user=user, product=self.product, rating=4, comment="Good")
        response = self.client.get(reverse("store:product-detail", args=[self.product.slug]))
        self.assertContains(response, '"hasMerchantReturnPolicy"')
        self.assertContains(response, '"shippingDetails"')
        self.assertContains(response, '"priceValidUntil"')
        self.assertContains(response, '"aggregateRating"')
        self.assertContains(response, '"ratingValue": "4.0"')


class DeliveryPromiseAndMerchandisingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.category, self.brand, self.product = _make_catalog("Promise")

    def test_announcement_bar_matches_the_fee_policy(self):
        response = self.client.get(reverse("store:home"))
        self.assertContains(response, "Free delivery in Addis Ababa on orders over 3,500 ETB")
        self.assertNotContains(response, "<p>Free delivery in Addis Ababa. Shop new arrivals now.</p>")

    def test_featured_collection_without_live_products_is_not_shown(self):
        Category.objects.create(title="Cosmetics", slug="cosmetics", is_active=True, is_featured=True)
        Brand.objects.create(title="Adidas", slug="adidas", is_active=True, is_featured=True)
        response = self.client.get(reverse("store:home"))
        self.assertNotContains(response, "Cosmetics")
        self.assertNotContains(response, "Adidas")
        self.assertContains(response, self.category.title)

    def test_filter_sidebar_only_lists_collections_with_live_products(self):
        Category.objects.create(title="Emptyland", slug="emptyland", is_active=True, is_featured=False)
        response = self.client.get(reverse("store:all-products"))
        self.assertNotContains(response, "Emptyland")
        self.assertContains(response, self.category.title)

    def test_prices_use_thousands_separators(self):
        self.product.price = Decimal("6000.00")
        self.product.save()
        response = self.client.get(reverse("store:product-detail", args=[self.product.slug]))
        self.assertContains(response, "6,000 ETB")
        self.assertNotContains(response, "6000.00 ETB")

    def test_stock_message_uses_availability_language_by_default(self):
        response = self.client.get(reverse("store:product-detail", args=[self.product.slug]))
        self.assertContains(response, "In stock")
        self.assertNotContains(response, "10 in stock")

    @override_settings(STORE_SHOW_STOCK_COUNTS=True)
    def test_stock_message_shows_counts_when_enabled(self):
        response = self.client.get(reverse("store:product-detail", args=[self.product.slug]))
        self.assertContains(response, "10 in stock")

    @override_settings(INVENTORY_DEFAULT_STOCK_PER_SIZE=0)
    def test_default_stock_per_size_is_configurable(self):
        set_product_sizes(self.product, ["S", "M", "L", "XL"])
        self.assertEqual(_stock_for(self.product, "XL"), 0)
        self.assertEqual(_stock_for(self.product, "M"), 10, "existing sizes keep their counts")

    def test_empty_states_never_mention_admin(self):
        Product.objects.update(is_active=False)
        cache.clear()
        response = self.client.get(reverse("store:all-products"))
        self.assertNotContains(response, "in admin")
        self.assertContains(response, "Join the channel")


class OrderGroupCheckoutTests(TestCase):
    def setUp(self):
        cache.clear()
        BackgroundTask.objects.all().delete()
        self.category, self.brand, self.product = _make_catalog("Group")
        self.product.price = Decimal("1000.00")
        self.product.save()

    def _guest_checkout(self, **overrides):
        self.client.post(reverse("store:add-to-cart"), {"prod_id": self.product.id, "size": "M"})
        payload = {
            "full_name": "Guest Buyer",
            "phone": "+251 911 000 111",
            "email": "guest@example.com",
            "city": "Addis Ababa",
            "address": "Bole Atlas street 12",
        }
        payload.update(overrides)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse("store:checkout"), payload)

    def test_checkout_creates_group_with_number_snapshot_and_delivery_fee(self):
        response = self._guest_checkout()
        self.assertEqual(response.status_code, 302)
        group = OrderGroup.objects.get()
        self.assertTrue(group.number.startswith("ZT-"))
        self.assertEqual(group.contact["phone"], "0911000111", "phone is normalised at checkout")
        self.assertEqual(group.contact["email"], "guest@example.com")
        self.assertEqual(group.subtotal, Decimal("1000.00"))
        self.assertEqual(group.delivery_fee, Decimal("80.00"))
        self.assertEqual(group.total, Decimal("1080.00"))
        self.assertEqual(group.lines.count(), 1)
        self.assertEqual(response.url, reverse("store:order-confirmation", kwargs={"token": group.claim_token}))

    def test_free_delivery_over_threshold_and_outside_addis_fee(self):
        self.assertEqual(delivery_fee_for("Addis Ababa", Decimal("3500")), Decimal("0.00"))
        self.assertEqual(delivery_fee_for("addis abeba", Decimal("100")), Decimal("80.00"))
        self.assertEqual(delivery_fee_for("Hawassa", Decimal("9000")), Decimal("180.00"))

    def test_confirmation_page_shows_receipt_and_tracks_purchase_once(self):
        self._guest_checkout()
        group = OrderGroup.objects.get()
        url = reverse("store:order-confirmation", kwargs={"token": group.claim_token})

        first = self.client.get(url)
        self.assertEqual(first.status_code, 200)
        self.assertContains(first, group.number)
        self.assertContains(first, "1,080 ETB")
        self.assertContains(first, "Cash on delivery")
        self.assertContains(first, 'id="ga-purchase-data"')
        self.assertContains(first, 'name="robots" content="noindex, nofollow"')

        second = self.client.get(url)
        self.assertNotContains(second, 'id="ga-purchase-data"', msg_prefix="purchase must be emitted once")

    def test_guest_can_see_their_orders_from_the_session(self):
        self._guest_checkout()
        response = self.client.get(reverse("store:orders"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, OrderGroup.objects.get().number)

    @override_settings(TASKS_EAGER=True)
    def test_checkout_enqueues_sms_email_task_and_sends_email(self):
        with patch("store.services.notifications.send_sms", return_value=True) as sms_mock:
            self._guest_checkout()
        task = BackgroundTask.objects.get(task_type=BackgroundTask.TYPE_CUSTOMER_ORDER_MESSAGES)
        self.assertEqual(task.status, BackgroundTask.STATUS_DONE)
        sms_mock.assert_called_once()
        self.assertEqual(sms_mock.call_args.args[0], "0911000111")
        self.assertIn("ZT-", sms_mock.call_args.args[1])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["guest@example.com"])
        self.assertIn(OrderGroup.objects.get().number, mail.outbox[0].subject)

    def test_staff_notification_carries_order_number_and_totals(self):
        self._guest_checkout()
        task = BackgroundTask.objects.get(task_type=BackgroundTask.TYPE_TELEGRAM_ORDER_NOTIFY)
        self.assertEqual(task.payload["order_number"], OrderGroup.objects.get().number)
        self.assertEqual(task.payload["delivery_fee"], "80.00")
        self.assertEqual(task.payload["grand_total"], "1080.00")

    def test_invalid_phone_is_rejected_at_checkout(self):
        response = self._guest_checkout(phone="12345")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("store:cart"))
        self.assertFalse(OrderGroup.objects.exists())

    def test_registered_checkout_snapshots_address(self):
        user = User.objects.create_user(username="0911600000", password="test-pass-123", first_name="Sara")
        Address.objects.create(user=user, address="Old Airport", city="Addis Ababa", phone="0911600000")
        Cart.objects.create(user=user, product=self.product, quantity=1, size="M")
        self.client.login(username="0911600000", password="test-pass-123")
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("store:checkout"))
        group = OrderGroup.objects.get()
        self.assertEqual(group.contact["address"], "Old Airport")
        # Later address changes never rewrite history.
        Address.objects.create(user=user, address="New Place", city="Adama", phone="0911600000")
        line = group.lines.get()
        self.assertEqual(line.customer_location, "Old Airport, Addis Ababa")


class CancellationRestoresStockTests(TestCase):
    def setUp(self):
        cache.clear()
        self.category, self.brand, self.product = _make_catalog("Cancel")
        self.user = User.objects.create_user(username="0911610000", password="test-pass-123")
        Address.objects.create(user=self.user, address="Bole", city="Addis Ababa", phone="0911610000")
        Cart.objects.create(user=self.user, product=self.product, quantity=2, size="M")
        self.client.login(username="0911610000", password="test-pass-123")
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("store:checkout"))
        self.order = Order.objects.get(user=self.user)
        self.product.refresh_from_db()

    def test_customer_cancel_returns_units(self):
        self.assertEqual(_stock_for(self.product, "M"), 8)
        self.assertEqual(self.product.stock_quantity, 28)
        response = self.client.post(reverse("store:cancel-order", args=[self.order.id]))
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.order.status, "Cancelled")
        self.assertTrue(self.order.stock_restored)
        self.assertEqual(_stock_for(self.product, "M"), 10)
        self.assertEqual(self.product.stock_quantity, 30)

    def test_cancel_is_idempotent(self):
        cancel_order_line(self.order)
        cancel_order_line(self.order)
        self.assertEqual(_stock_for(self.product, "M"), 10)

    def test_dashboard_cancel_restores_and_delivered_invites_review(self):
        staff = User.objects.create_user(username="0911620000", password="test-pass-123", is_staff=True)
        self.client.login(username="0911620000", password="test-pass-123")
        BackgroundTask.objects.all().delete()
        with override_settings(TASKS_EAGER=False):
            self.client.post(reverse("store:dashboard-orders"), {"order_id": self.order.id, "status": "Delivered", "action": "single"})
        self.assertTrue(BackgroundTask.objects.filter(task_type=BackgroundTask.TYPE_CUSTOMER_REVIEW_INVITE, payload__order_id=self.order.id).exists())

        other_line = Order.objects.create(user=self.user, product=self.product, quantity=1, size="M", price_at_purchase=Decimal("100"), line_total=Decimal("100"))
        self.client.post(reverse("store:dashboard-orders"), {"action": "bulk", "order_ids": [other_line.id], "bulk_status": "Cancelled"})
        other_line.refresh_from_db()
        self.assertEqual(other_line.status, "Cancelled")
        self.assertEqual(_stock_for(self.product, "M"), 9, "bulk cancel returned the extra unit")
        self.assertEqual(staff.is_staff, True)

    def test_cancelled_sold_out_product_comes_back_on_shelf(self):
        Product.objects.filter(pk=self.product.pk).update(stock_quantity=0, is_sold_out=True)
        ProductSizeStock.objects.filter(product=self.product).update(quantity=0)
        self.product.refresh_from_db()
        cancel_order_line(self.order)
        self.product.refresh_from_db()
        self.assertFalse(self.product.is_sold_out)
        self.assertEqual(_stock_for(self.product, "M"), 2)


class PhoneNormalisationTests(TestCase):
    def test_variants_normalise_to_local_form(self):
        for raw in ("0911234567", "911234567", "+251911234567", "251 911 234 567", "00251-911-234-567", "+251 (911) 234.567"):
            self.assertEqual(normalize_et_phone(raw), "0911234567", raw)
        self.assertEqual(normalize_et_phone("0712345678"), "0712345678")
        self.assertEqual(to_e164("0911234567"), "+251911234567")
        for bad in ("12345", "0811234567", "091123456", "abc", ""):
            self.assertIsNone(normalize_et_phone(bad), bad)

    def test_registration_normalises_and_dedupes_phone(self):
        payload = {
            "full_name": "Jane Doe",
            "username": "+251 911 777 000",
            "email": "jane@example.com",
            "address": "Bole",
            "city": "Addis Ababa",
            "password1": "StrongPass!2026",
            "password2": "StrongPass!2026",
        }
        response = self.client.post(reverse("store:register"), payload)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username="0911777000").exists())
        self.client.logout()
        payload["email"] = "other@example.com"
        duplicate = self.client.post(reverse("store:register"), {**payload, "username": "0911777000"})
        self.assertEqual(duplicate.status_code, 200)
        self.assertContains(duplicate, "already exists")

    def test_login_accepts_international_spelling(self):
        User.objects.create_user(username="0911888000", password="test-pass-123")
        self.assertTrue(self.client.login(username="+251911888000", password="test-pass-123"))


class ReviewInviteTests(TestCase):
    def setUp(self):
        cache.clear()
        self.category, self.brand, self.product = _make_catalog("Invite")
        self.group = OrderGroup.objects.create(
            number="ZT-260903-TEST",
            contact={"full_name": "Hanna Bekele", "phone": "0911700100", "city": "Addis Ababa", "address": "Kazanchis", "email": "hanna@example.com"},
            subtotal=Decimal("100"), total=Decimal("180"), delivery_fee=Decimal("80"),
        )
        self.order = Order.objects.create(
            group=self.group, product=self.product, quantity=1, size="M",
            price_at_purchase=Decimal("100"), line_total=Decimal("100"), status="Delivered",
        )

    def test_invite_handler_prefers_sms_and_marks_invited(self):
        from store.services.notifications import send_review_invite

        with patch("store.services.notifications.send_sms", return_value=True) as sms_mock:
            send_review_invite({"order_id": self.order.id})
        self.order.refresh_from_db()
        self.assertTrue(self.order.review_token)
        self.assertIsNotNone(self.order.review_invited_at)
        self.assertIn(f"/review/{self.order.review_token}/", sms_mock.call_args.args[1])
        # Second run is a no-op.
        with patch("store.services.notifications.send_sms", return_value=True) as again:
            send_review_invite({"order_id": self.order.id})
        again.assert_not_called()

    def test_invite_falls_back_to_email_when_sms_disabled(self):
        from store.services.notifications import send_review_invite

        with override_settings(SMS_BACKEND="disabled"):
            send_review_invite({"order_id": self.order.id})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["hanna@example.com"])

    def test_token_link_posts_a_verified_review_without_login(self):
        token = self.order.ensure_review_token()
        url = reverse("store:review-invite", kwargs={"token": token})
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, self.product.title)

        response = self.client.post(url, {"reviewer_name": "Hanna", "rating": 5, "title": "Perfect", "comment": "Fits like a glove", "fit_feedback": ProductReview.FIT_TRUE_TO_SIZE})
        self.assertEqual(response.status_code, 302)
        review = ProductReview.objects.get(order=self.order)
        self.assertTrue(review.is_verified_purchase)
        self.assertIsNone(review.user)
        self.assertEqual(review.reviewer_name, "Hanna")

        detail = self.client.get(reverse("store:product-detail", args=[self.product.slug]))
        self.assertContains(detail, "Verified purchase")
        self.assertContains(detail, "Hanna")

    def test_bad_or_undelivered_token_is_404(self):
        self.assertEqual(self.client.get(reverse("store:review-invite", kwargs={"token": "nope"})).status_code, 404)
        self.order.status = "Pending"
        self.order.save()
        token = self.order.ensure_review_token()
        self.assertEqual(self.client.get(reverse("store:review-invite", kwargs={"token": token})).status_code, 404)

    def test_logged_in_review_is_verified_when_a_delivered_order_exists(self):
        user = User.objects.create_user(username="0911700200", password="test-pass-123")
        Order.objects.create(user=user, product=self.product, quantity=1, size="M", price_at_purchase=Decimal("100"), line_total=Decimal("100"), status="Delivered")
        self.client.login(username="0911700200", password="test-pass-123")
        self.client.post(reverse("store:submit-review", args=[self.product.slug]), {"rating": 4, "comment": "Nice", "fit_feedback": ""})
        self.assertTrue(ProductReview.objects.get(user=user, product=self.product).is_verified_purchase)


class SecurityHardeningTests(TestCase):
    def setUp(self):
        cache.clear()
        User.objects.create_user(username="0911770000", password="test-pass-123")

    def test_csp_header_on_html_responses(self):
        response = self.client.get(reverse("store:home"))
        self.assertIn("Content-Security-Policy", response)
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])
        robots = self.client.get("/robots.txt")
        self.assertNotIn("Content-Security-Policy", robots)

    @override_settings(LOGIN_RATE_LIMIT_ATTEMPTS=3)
    def test_login_is_rate_limited_after_repeated_failures(self):
        for _ in range(3):
            response = self.client.post(reverse("store:login"), {"username": "0911770000", "password": "wrong"})
            self.assertEqual(response.status_code, 200)
        blocked = self.client.post(reverse("store:login"), {"username": "0911770000", "password": "test-pass-123"})
        self.assertEqual(blocked.status_code, 429)
        self.assertContains(blocked, "Too many attempts", status_code=429)

    def test_successful_login_clears_counter(self):
        self.client.post(reverse("store:login"), {"username": "0911770000", "password": "wrong"})
        ok = self.client.post(reverse("store:login"), {"username": "0911770000", "password": "test-pass-123"})
        self.assertEqual(ok.status_code, 302)

    def test_static_urls_carry_content_hash(self):
        response = self.client.get(reverse("store:home"))
        self.assertRegex(response.content.decode(), r"asset/css/zent-storefront\.css\?v=[0-9a-f]{10}")
        self.assertNotContains(response, "style.min.css")
        self.assertNotContains(response, "jquery")


class SmsBackendTests(TestCase):
    def test_console_backend_sends_only_to_valid_numbers(self):
        from store.sms import send_sms

        with override_settings(SMS_BACKEND="console"):
            self.assertTrue(send_sms("+251 911 234 567", "hello"))
            self.assertFalse(send_sms("12345", "hello"))
        with override_settings(SMS_BACKEND="disabled"):
            self.assertFalse(send_sms("0911234567", "hello"))

    def test_http_backend_posts_rendered_template(self):
        from store.sms import send_sms

        class _Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        with override_settings(SMS_BACKEND="http", SMS_HTTP_URL="https://sms.example/send", SMS_HTTP_BODY='{"to": "{to}", "text": "{message}"}'), patch("store.sms.request.urlopen", return_value=_Resp()) as urlopen:
            self.assertTrue(send_sms("0911234567", "Order ZT-1 received"))
        sent = json.loads(urlopen.call_args.args[0].data.decode())
        self.assertEqual(sent, {"to": "+251911234567", "text": "Order ZT-1 received"})

    def test_dispatch_status_sends_sms(self):
        from store.services.notifications import send_status_sms

        category, brand, product = _make_catalog("Sms")
        group = OrderGroup.objects.create(number="ZT-260903-SMS1", contact={"phone": "0911700300", "full_name": "A"}, total=Decimal("180"))
        order = Order.objects.create(group=group, product=product, quantity=1, size="M", price_at_purchase=Decimal("100"), line_total=Decimal("100"))
        with patch("store.services.notifications.send_sms", return_value=True) as sms_mock:
            self.assertTrue(send_status_sms(order, "On The Way"))
            self.assertFalse(send_status_sms(order, "Packed"))
        self.assertIn("on the way", sms_mock.call_args.args[1])


@override_settings(ONLINE_PAYMENTS_ENABLED=True, CHAPA_SECRET_KEY="test-secret", CHAPA_WEBHOOK_SECRET="hook-secret")
class ChapaPaymentTests(TestCase):
    def setUp(self):
        cache.clear()
        BackgroundTask.objects.all().delete()
        self.category, self.brand, self.product = _make_catalog("Chapa")
        self.product.price = Decimal("2000.00")
        self.product.save()

    def _checkout(self, payment_method="chapa"):
        self.client.post(reverse("store:add-to-cart"), {"prod_id": self.product.id, "size": "M"})
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                reverse("store:checkout"),
                {"full_name": "Pay Now", "phone": "0911900900", "city": "Addis Ababa", "address": "Sarbet", "payment_method": payment_method},
            )

    def test_cart_offers_payment_choice_when_enabled(self):
        self.client.post(reverse("store:add-to-cart"), {"prod_id": self.product.id, "size": "M"})
        response = self.client.get(reverse("store:cart"))
        self.assertContains(response, 'name="payment_method" value="chapa"')
        self.assertContains(response, "Telebirr")

    def test_chapa_checkout_redirects_to_hosted_page(self):
        with patch("store.payments.chapa.initialize_payment", return_value="https://checkout.chapa.co/pay/abc") as init:
            response = self._checkout()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "https://checkout.chapa.co/pay/abc")
        group = OrderGroup.objects.get()
        self.assertEqual(group.payment_method, OrderGroup.PAYMENT_CHAPA)
        self.assertEqual(group.payment_status, OrderGroup.PAYMENT_PENDING)
        self.assertEqual(init.call_args.args[0], group)

    def test_chapa_outage_falls_back_to_cash_on_delivery(self):
        from store.payments.chapa import ChapaError

        with patch("store.payments.chapa.initialize_payment", side_effect=ChapaError("Chapa could not be reached.")):
            response = self._checkout()
        group = OrderGroup.objects.get()
        self.assertEqual(response.url, reverse("store:order-confirmation", kwargs={"token": group.claim_token}))
        self.assertEqual(group.payment_method, OrderGroup.PAYMENT_COD)

    def test_return_url_verifies_before_marking_paid(self):
        with patch("store.payments.chapa.initialize_payment", return_value="https://checkout.chapa.co/pay/abc"):
            self._checkout()
        group = OrderGroup.objects.get()
        tx_ref = f"{group.number}-{group.id}"
        verified = {"status": "success", "amount": "2080.00", "currency": "ETB", "reference": "CHP-1"}
        with patch("store.payments.chapa.verify_payment", return_value=verified):
            response = self.client.get(reverse("store:chapa-return"), {"tx_ref": tx_ref})
        self.assertEqual(response.status_code, 302)
        group.refresh_from_db()
        self.assertEqual(group.payment_status, OrderGroup.PAYMENT_PAID)
        self.assertEqual(group.payment_reference, "CHP-1")

    def test_return_with_short_payment_is_not_marked_paid(self):
        with patch("store.payments.chapa.initialize_payment", return_value="https://checkout.chapa.co/pay/abc"):
            self._checkout()
        group = OrderGroup.objects.get()
        with patch("store.payments.chapa.verify_payment", return_value={"status": "success", "amount": "10.00", "currency": "ETB"}):
            self.client.get(reverse("store:chapa-return"), {"tx_ref": f"{group.number}-{group.id}"})
        group.refresh_from_db()
        self.assertEqual(group.payment_status, OrderGroup.PAYMENT_PENDING)

    def test_webhook_requires_valid_signature(self):
        with patch("store.payments.chapa.initialize_payment", return_value="https://checkout.chapa.co/pay/abc"):
            self._checkout()
        group = OrderGroup.objects.get()
        body = json.dumps({"tx_ref": f"{group.number}-{group.id}", "status": "success"}).encode()
        rejected = self.client.post(reverse("store:chapa-webhook"), body, content_type="application/json", HTTP_CHAPA_SIGNATURE="bad")
        self.assertEqual(rejected.status_code, 403)

        signature = hmac.new(b"hook-secret", body, hashlib.sha256).hexdigest()
        with patch("store.payments.chapa.verify_payment", return_value={"status": "success", "amount": "2080.00", "currency": "ETB"}):
            accepted = self.client.post(reverse("store:chapa-webhook"), body, content_type="application/json", HTTP_CHAPA_SIGNATURE=signature)
        self.assertEqual(accepted.status_code, 200)
        group.refresh_from_db()
        self.assertEqual(group.payment_status, OrderGroup.PAYMENT_PAID)


class AnalyticsAndSearchLogTests(TestCase):
    def setUp(self):
        cache.clear()
        self.category, self.brand, self.product = _make_catalog("Ga")

    def test_add_to_cart_emits_ga_trigger_header(self):
        response = self.client.post(reverse("store:add-to-cart"), {"prod_id": self.product.id, "size": "M"}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        trigger = json.loads(response["HX-Trigger"])
        self.assertEqual(trigger["zent:add_to_cart"]["items"][0]["item_id"], self.product.sku)

    @override_settings(GA_MEASUREMENT_ID="G-TEST123")
    def test_ga_snippet_and_view_item_payload(self):
        response = self.client.get(reverse("store:product-detail", args=[self.product.slug]))
        self.assertContains(response, "G-TEST123")
        self.assertContains(response, 'id="ga-view-item-data"')

    @override_settings(GA_MEASUREMENT_ID="")
    def test_ga_snippet_absent_when_unset(self):
        response = self.client.get(reverse("store:home"))
        self.assertNotContains(response, "googletagmanager")

    def test_zero_result_search_is_logged_and_surfaced_in_dashboard(self):
        self.client.get(reverse("store:search"), {"q": "leather jacket"})
        self.client.get(reverse("store:search"), {"q": "Leather Jacket"})
        self.client.get(reverse("store:search"), {"q": self.product.title})
        self.assertEqual(SearchLog.objects.filter(result_count=0).count(), 2)
        self.assertEqual(SearchLog.objects.filter(result_count__gt=0).count(), 1)

        User.objects.create_user(username="0911990000", password="test-pass-123", is_staff=True)
        self.client.login(username="0911990000", password="test-pass-123")
        dashboard = self.client.get(reverse("store:dashboard-home"))
        self.assertContains(dashboard, "leather jacket")
        self.assertContains(dashboard, "Conversion funnel")


class TranslationTests(TestCase):
    def setUp(self):
        cache.clear()
        _make_catalog("Lang")

    def test_language_switch_renders_amharic_chrome(self):
        response = self.client.post(reverse("store:set-language"), {"language": "am", "next": "/"}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'lang="am"')
        self.assertContains(response, "ጋሪ")  # Cart
        self.assertContains(response, "ሲደርስ ይክፈሉ")  # Pay on delivery

    def test_default_language_is_english(self):
        response = self.client.get(reverse("store:home"))
        self.assertContains(response, 'lang="en"')
        self.assertContains(response, "Pay on delivery")


class TelegramCrossLinkTests(TestCase):
    def setUp(self):
        self.category, self.brand, self.product = _make_catalog("Link")

    @override_settings(SITE_URL="https://zentanee.example")
    def test_channel_caption_links_back_to_the_site(self):
        from store.telegram_notify import _product_caption, product_site_url

        self.assertEqual(product_site_url(self.product), f"https://zentanee.example/product/{self.product.slug}/")
        self.assertIn("zentanee.example/product/", _product_caption(self.product))

    def test_pdp_offers_order_on_telegram_when_bot_configured(self):
        with patch("store.telegram_notify._customer_bot_settings", return_value=("tok", "@zentanee_channel", "zentanee_order_bot")):
            response = self.client.get(reverse("store:product-detail", args=[self.product.slug]))
        self.assertContains(response, f"https://t.me/zentanee_order_bot?start=order_{self.product.id}")
        self.assertContains(response, "Order on Telegram")


class InlineTaskRegistryTests(TestCase):
    def test_new_task_types_are_registered(self):
        registry = task_queue._registry()
        self.assertIn(BackgroundTask.TYPE_CUSTOMER_ORDER_MESSAGES, registry)
        self.assertIn(BackgroundTask.TYPE_CUSTOMER_REVIEW_INVITE, registry)
        self.assertIn("customer_order_messages", task_queue.INLINE_TASK_TYPES)


class PageSmokeTests(TestCase):
    """Every public and staff page renders: catches template errors the
    behaviour tests above do not reach."""

    def setUp(self):
        cache.clear()
        self.category, self.brand, self.product = _make_catalog("Smoke")
        self.staff = User.objects.create_user(username="0911995000", password="test-pass-123", is_staff=True)
        self.customer = User.objects.create_user(username="0911995001", password="test-pass-123", email="c@example.com")

    def test_public_pages_render(self):
        for name in ("store:privacy", "store:terms", "store:faq", "store:contact", "store:about", "store:delivery-returns",
                     "store:all-categories", "store:all-brands", "store:sale-products", "store:password-reset", "store:register", "store:login"):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(reverse("store:brand-products", args=[self.brand.slug])).status_code, 200)
        self.assertEqual(self.client.get(reverse("store:category-products", args=[self.category.slug])).status_code, 200)

    def test_branded_404_page(self):
        response = self.client.get("/definitely-not-a-collection/")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "We couldn't find that page.", status_code=404)
        self.assertContains(response, "spring-bottom-nav", status_code=404)

    def test_customer_pages_render(self):
        self.client.login(username="0911995001", password="test-pass-123")
        for name in ("store:profile", "store:orders", "store:affiliate-dashboard", "store:add-address", "store:password-change"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_staff_pages_render(self):
        self.client.login(username="0911995000", password="test-pass-123")
        for name in ("store:dashboard-home", "store:dashboard-orders", "store:dashboard-products", "store:dashboard-product-create"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        self.assertEqual(self.client.get(reverse("store:dashboard-product-edit", args=[self.product.id])).status_code, 200)
