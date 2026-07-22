from decimal import Decimal
from io import BytesIO
import json
import tempfile
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from . import ai_enrichment
from . import tasks as task_queue
from .models import (
    Address,
    AffiliateCommission,
    AffiliateProfile,
    BackgroundTask,
    Brand,
    Cart,
    Category,
    Order,
    Product,
    ProductAIDraft,
    ProductAIDraftImage,
    Wishlist,
)
from .services.inventory import set_product_sizes
from .telegram_notify import suspend_telegram_autopublish


class StoreFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="0911000000", password="test-pass-123")
        self.other_user = User.objects.create_user(username="0911222333", password="test-pass-123")
        self.staff_user = User.objects.create_user(
            username="0911444555",
            password="test-pass-123",
            is_staff=True,
            first_name="Ops",
            last_name="Lead",
        )

        self.category = Category.objects.create(
            title="Rings",
            slug="rings",
            is_active=True,
            is_featured=True,
        )
        self.brand = Brand.objects.create(
            title="Zent",
            slug="zent",
            is_active=True,
            is_featured=True,
        )
        self.product = Product.objects.create(
            title="Silver Ring",
            slug="silver-ring",
            sku="SKU-100",
            short_description="A classic ring",
            product_image="product/test.jpg",
            price=Decimal("100.00"),
            category=self.category,
            brand=self.brand,
            is_active=True,
            is_featured=True,
            is_sold_out=False,
        )
        set_product_sizes(self.product, ["S", "M", "L"])

    def _make_uploaded_image(self, *, name="identifier.jpg", color="navy"):
        image_bytes = BytesIO()
        Image.new("RGB", (40, 40), color=color).save(image_bytes, format="JPEG")
        image_bytes.seek(0)
        return SimpleUploadedFile(
            name,
            image_bytes.read(),
            content_type="image/jpeg",
        )

    def _create_ai_draft(self):
        draft = ProductAIDraft.objects.create(
            created_by=self.staff_user,
            sku="AI-SKU-1",
            vendor_hint="Mercato Studio",
            price=Decimal("349.00"),
            reference_image=self._make_uploaded_image(name="ai-ref.jpg", color="purple"),
            status=ProductAIDraft.STATUS_SUCCEEDED,
            response_payload={
                "catalog_fields": {
                    "title": "Purple Abaya",
                    "slug_hint": "purple-abaya",
                    "short_description": "Elegant modest abaya.",
                    "detail_description": "A flowing modest abaya with soft drape.",
                    "material": "Cotton blend",
                    "color": "Purple",
                    "fit_notes": "Relaxed fit.",
                    "care_notes": "Hand wash cold.",
                    "delivery_note": "Fast delivery.",
                    "return_note": "Return within 3 days.",
                    "suggested_category": "Rings",
                    "suggested_brand": "Zent",
                    "product_type": "Abaya",
                },
                "confidence": {
                    "overall": "medium",
                    "reasoning_notes": ["Good color match."],
                    "needs_manual_review": ["Confirm fabric blend."],
                },
                "sources": [],
                "search_strategy": {
                    "vendor_hint": "Mercato Studio",
                    "exact_queries": ["AI-SKU-1"],
                    "fallback_queries": ["purple abaya"],
                },
                "image_plan": {
                    "reference_preservation_notes": "Keep the product unchanged.",
                    "negative_prompt": "No extra garments.",
                    "shots": [
                        {
                            "name": "Studio White Hero",
                            "prompt": "Clean white hero with true color fidelity.",
                            "aspect_ratio": "4:5",
                            "priority": 1,
                        },
                        {
                            "name": "Soft Editorial Portrait",
                            "prompt": "Premium neutral backdrop with fabric drape.",
                            "aspect_ratio": "4:5",
                            "priority": 2,
                        },
                    ],
                },
            },
            image_plan={
                "shots": [
                    {
                        "name": "Studio White Hero",
                        "prompt": "Clean white hero with true color fidelity.",
                        "aspect_ratio": "4:5",
                        "priority": 1,
                    },
                    {
                        "name": "Soft Editorial Portrait",
                        "prompt": "Premium neutral backdrop with fabric drape.",
                        "aspect_ratio": "4:5",
                        "priority": 2,
                    },
                ]
            },
        )
        return draft

    def _mock_ai_result(self, *, title="Purple Abaya"):
        return {
            "catalog_fields": {
                "title": title,
                "slug_hint": "purple-abaya",
                "short_description": "Elegant modest abaya.",
                "detail_description": "A flowing modest abaya with soft drape.",
                "material": "Cotton blend",
                "color": "Purple",
                "fit_notes": "Relaxed fit.",
                "care_notes": "Hand wash cold.",
                "delivery_note": "Fast delivery.",
                "return_note": "Return within 3 days.",
                "suggested_category": "Rings",
                "suggested_brand": "Zent",
                "product_type": "Abaya",
            },
            "confidence": {
                "overall": "medium",
                "reasoning_notes": ["Good color match."],
                "needs_manual_review": ["Confirm fabric blend."],
            },
            "sources": [],
            "search_strategy": {
                "vendor_hint": "Mercato Studio",
                "exact_queries": ["AI-SKU-1"],
                "fallback_queries": ["purple abaya"],
            },
            "seo": {
                "seo_title": "Purple Abaya | Zent",
                "meta_description": "Elegant modest abaya.",
                "image_alt_text": "Purple abaya product image",
                "focus_keyphrase": "purple abaya",
            },
            "image_plan": {
                "reference_preservation_notes": "Keep the product unchanged.",
                "negative_prompt": "No extra garments.",
                "shots": [
                    {
                        "name": "Studio White Hero",
                        "prompt": "Clean white hero with true color fidelity.",
                        "aspect_ratio": "4:5",
                        "priority": 1,
                    },
                    {
                        "name": "Soft Editorial Portrait",
                        "prompt": "Premium neutral backdrop with fabric drape.",
                        "aspect_ratio": "4:5",
                        "priority": 2,
                    },
                ],
            },
            "generation_package": {
                "mode": "reference-guided",
                "reference_strength": "high",
                "notes": "Keep the item unchanged.",
                "shots": [
                    {
                        "name": "Studio White Hero",
                        "prompt": "Clean white hero with true color fidelity.",
                        "negative_prompt": "No extra garments.",
                        "aspect_ratio": "4:5",
                        "reference_images": ["primary"],
                        "priority": 1,
                    }
                ],
            },
        }

    def test_add_to_cart_requires_post(self):
        self.client.login(username="0911000000", password="test-pass-123")

        response = self.client.get(reverse("store:add-to-cart"), {"prod_id": self.product.id})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Cart.objects.filter(user=self.user).count(), 0)

    def test_add_to_cart_requires_size_when_product_has_sizes(self):
        self.client.login(username="0911000000", password="test-pass-123")

        response = self.client.post(reverse("store:add-to-cart"), {"prod_id": self.product.id})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Cart.objects.filter(user=self.user).count(), 0)

    def test_user_cannot_remove_another_users_cart_item(self):
        foreign_cart = Cart.objects.create(user=self.other_user, product=self.product, quantity=1)
        self.client.login(username="0911000000", password="test-pass-123")

        response = self.client.post(reverse("store:remove-cart", args=[foreign_cart.id]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Cart.objects.filter(id=foreign_cart.id).exists())

    def test_checkout_requires_post(self):
        Cart.objects.create(user=self.user, product=self.product, quantity=1, size="M")
        self.client.login(username="0911000000", password="test-pass-123")

        response = self.client.get(reverse("store:checkout"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Cart.objects.filter(user=self.user).count(), 1)

    def test_checkout_creates_affiliate_commission(self):
        affiliate_owner = User.objects.create_user(username="0911333444", password="test-pass-123")
        affiliate_profile = AffiliateProfile.objects.create(
            user=affiliate_owner,
            code="aff-test-code",
            is_active=True,
        )
        Address.objects.create(
            user=self.user,
            address="Bole Atlas",
            city="Addis Ababa",
            phone=self.user.username,
        )

        Cart.objects.create(user=self.user, product=self.product, quantity=2, size="M")
        self.client.login(username="0911000000", password="test-pass-123")

        session = self.client.session
        session["affiliate_profile_id"] = affiliate_profile.id
        session.save()

        response = self.client.post(reverse("store:checkout"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(AffiliateCommission.objects.count(), 1)
        commission = AffiliateCommission.objects.first()
        self.assertEqual(str(commission.amount), "10.00")
        self.assertEqual(commission.affiliate_id, affiliate_profile.id)

    def test_self_referral_does_not_generate_commission(self):
        affiliate_profile = AffiliateProfile.objects.create(
            user=self.user,
            code="aff-self-code",
            is_active=True,
        )
        Address.objects.create(
            user=self.user,
            address="Megenagna",
            city="Addis Ababa",
            phone=self.user.username,
        )

        Cart.objects.create(user=self.user, product=self.product, quantity=1, size="M")
        self.client.login(username="0911000000", password="test-pass-123")

        session = self.client.session
        session["affiliate_profile_id"] = affiliate_profile.id
        session.save()

        response = self.client.post(reverse("store:checkout"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(AffiliateCommission.objects.count(), 0)

    def test_track_affiliate_link_sets_session_and_redirects(self):
        affiliate_owner = User.objects.create_user(username="0911999000", password="test-pass-123")
        affiliate_profile = AffiliateProfile.objects.create(
            user=affiliate_owner,
            code="aff-route-code",
            is_active=True,
        )

        response = self.client.get(
            reverse("store:affiliate-track", args=[affiliate_profile.code]),
            {"next": f"/product/{self.product.slug}/"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, f"/product/{self.product.slug}/")
        self.assertEqual(self.client.session.get("affiliate_profile_id"), affiliate_profile.id)

    def test_registration_requires_address_fields(self):
        response = self.client.post(
            reverse("store:register"),
            {
                "full_name": "Jane Doe",
                "username": "0911777000",
                "email": "jane@example.com",
                "address": "",
                "city": "",
                "password1": "ComplexPass123!",
                "password2": "ComplexPass123!",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username="0911777000").exists())

    def test_registration_creates_address_and_name(self):
        response = self.client.post(
            reverse("store:register"),
            {
                "full_name": "Jane Doe",
                "username": "0911888999",
                "email": "jane2@example.com",
                "address": "Megenagna, near main square",
                "city": "Addis Ababa",
                "password1": "ComplexPass123!",
                "password2": "ComplexPass123!",
            },
        )

        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="0911888999")
        self.assertEqual(user.first_name, "Jane")
        self.assertEqual(user.last_name, "Doe")
        self.assertTrue(
            Address.objects.filter(
                user=user,
                address="Megenagna, near main square",
                city="Addis Ababa",
                phone="0911888999",
            ).exists()
        )

    @override_settings(MEDIA_ROOT=tempfile.gettempdir())
    def test_uploaded_product_image_keeps_original_format(self):
        # Cloudinary transforms at delivery time now — no server-side conversion.
        uploaded = self._make_uploaded_image(name="test-upload.jpg", color="red")

        product = Product.objects.create(
            title="Original Format Product",
            slug="original-format-product",
            sku="SKU-ORIG-1",
            short_description="Image upload test",
            product_image=uploaded,
            price=Decimal("150.00"),
            category=self.category,
            brand=self.brand,
            is_active=True,
            is_featured=False,
            is_sold_out=False,
        )

        self.assertTrue(product.product_image.name.lower().endswith(".jpg"))

    def test_cld_url_inserts_cloudinary_transforms(self):
        from store.templatetags.image_optim import cld_url

        source = "https://res.cloudinary.com/demo/image/upload/v1/media/product/ring.jpg"
        self.assertEqual(
            cld_url(source, 600),
            "https://res.cloudinary.com/demo/image/upload/f_auto,q_auto,c_limit,w_600/v1/media/product/ring.jpg",
        )
        # Non-Cloudinary URLs pass through untouched so local dev keeps working.
        self.assertEqual(cld_url("/media/product/ring.jpg", 600), "/media/product/ring.jpg")

    def test_cld_img_renders_srcset_and_lazy_loading(self):
        from store.templatetags.image_optim import cld_img

        source = "https://res.cloudinary.com/demo/image/upload/v1/media/product/ring.jpg"
        html = cld_img(source, width=420, alt="Silver Ring", html_width=420, html_height=520)
        self.assertIn('src="https://res.cloudinary.com/demo/image/upload/f_auto,q_auto,c_limit,w_420/v1/media/product/ring.jpg"', html)
        self.assertIn("f_auto,q_auto,c_limit,w_840", html)
        self.assertIn('loading="lazy"', html)
        self.assertIn('width="420" height="520"', html)

        hero = cld_img(source, width=900, alt="Hero", loading="eager", fetchpriority="high")
        self.assertIn('loading="eager"', hero)
        self.assertIn('fetchpriority="high"', hero)

    def test_staff_user_can_access_dashboard_home(self):
        self.client.login(username="0911444555", password="test-pass-123")

        response = self.client.get(reverse("store:dashboard-home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Control Room")

    def test_non_staff_user_is_redirected_from_dashboard(self):
        self.client.login(username="0911000000", password="test-pass-123")

        response = self.client.get(reverse("store:dashboard-home"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("store:home"))

    def test_staff_user_can_update_order_status_from_dashboard(self):
        order = self.product.order_set.create(
            user=self.user,
            quantity=1,
            size="M",
            price_at_purchase=Decimal("100.00"),
            line_total=Decimal("100.00"),
        )
        self.client.login(username="0911444555", password="test-pass-123")

        response = self.client.post(
            reverse("store:dashboard-orders"),
            {
                "order_id": order.id,
                "status": "Delivered",
                "next": reverse("store:dashboard-orders"),
            },
        )

        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, "Delivered")

    @override_settings(
        DEBUG=True,
        GEMINI_API_KEY="test-gemini-key",
        TASKS_EAGER=True,
        MEDIA_ROOT=tempfile.gettempdir(),
        DEFAULT_FILE_STORAGE="django.core.files.storage.FileSystemStorage",
    )
    @patch("store.services.enrichment.generate_product_ai_payload_for_draft")
    def test_staff_user_can_generate_ai_product_draft(self, generate_product_ai_payload_for_draft_mock):
        generate_product_ai_payload_for_draft_mock.return_value = self._mock_ai_result(title="Midnight Linen Shirt")

        self.client.login(username="0911444555", password="test-pass-123")

        response = self.client.post(
            reverse("store:dashboard-product-create"),
            {
                "sku": "SKU-500",
                "vendor_hint": "Mercato Studio",
                "price": "249.99",
                "generate_ai_draft": "1",
                "reference_image": self._make_uploaded_image(),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("ai_draft=", response.url)
        self.assertEqual(ProductAIDraft.objects.count(), 1)

        draft = ProductAIDraft.objects.get()
        self.assertEqual(draft.status, ProductAIDraft.STATUS_SUCCEEDED)
        self.assertEqual(draft.vendor_hint, "Mercato Studio")
        self.assertEqual(draft.response_payload["catalog_fields"]["title"], "Midnight Linen Shirt")
        self.assertEqual(self.client.session.get("dashboard_product_ai_draft_id"), draft.id)

        # The ready draft is turned into an unpublished product automatically,
        # matched to the existing collection/brand from the AI suggestions.
        product = Product.objects.get(sku="SKU-500")
        self.assertFalse(product.is_active)
        self.assertEqual(product.category, self.category)
        self.assertEqual(product.brand, self.brand)
        self.assertEqual(product.price, Decimal("249.99"))
        draft.refresh_from_db()
        self.assertEqual(draft.product_id, product.id)
        self.assertTrue(draft.response_payload["automation"]["product_created"])

        follow_up = self.client.get(response.url)
        self.assertEqual(follow_up.status_code, 200)
        self.assertContains(follow_up, "Midnight Linen Shirt")
        # The follow-up lands on the created product's editor: review card up
        # top, AI re-run tucked into a disclosure, full editor collapsed.
        self.assertContains(follow_up, "Regenerate with AI")
        self.assertContains(follow_up, "Edit details")

    @override_settings(DEBUG=True, GEMINI_API_KEY="test-gemini-key")
    def test_create_page_leads_with_ai_intake_and_collapsed_editor(self):
        self.client.login(username="0911444555", password="test-pass-123")

        response = self.client.get(reverse("store:dashboard-product-create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Post a product")
        self.assertContains(response, "Create product with AI")
        self.assertContains(response, "Fill in the details manually instead")
        # The manual editor ships hidden until revealed.
        self.assertRegex(
            response.content.decode(),
            r"data-zd-editor\s+hidden",
        )

    @override_settings(DEBUG=True, GEMINI_API_KEY="")
    def test_ai_draft_generation_requires_configured_key(self):
        self.client.login(username="0911444555", password="test-pass-123")

        response = self.client.post(
            reverse("store:dashboard-product-create"),
            {
                "sku": "SKU-200",
                "vendor_hint": "Bole Vendor",
                "price": "199.00",
                "generate_ai_draft": "1",
                "reference_image": self._make_uploaded_image(name="missing-key.jpg", color="green"),
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Set GEMINI_API_KEY in your environment before generating AI product drafts.")
        self.assertEqual(ProductAIDraft.objects.count(), 0)

    @override_settings(DEBUG=True, MEDIA_ROOT=tempfile.gettempdir())
    def test_staff_user_can_save_product_with_auto_size_inventory(self):
        draft = self._create_ai_draft()
        session = self.client.session
        session["dashboard_product_ai_draft_id"] = draft.id
        session.save()
        self.client.login(username="0911444555", password="test-pass-123")

        response = self.client.post(
            reverse("store:dashboard-product-create"),
            {
                "title": "Purple Abaya",
                "slug": "purple-abaya-ai",
                "sku": "AI-SKU-1",
                "short_description": "Elegant modest abaya.",
                "detail_description": "A flowing modest abaya with soft drape.",
                "material": "Cotton blend",
                "color": "Purple",
                "fit_notes": "Relaxed fit.",
                "care_notes": "Hand wash cold.",
                "delivery_note": "Fast delivery.",
                "return_note": "Return within 3 days.",
                "available_sizes": "S, M, L",
                "price": "349.00",
                "product_image": self._make_uploaded_image(name="product-primary.jpg", color="black"),
                "category": str(self.category.id),
                "brand": str(self.brand.id),
                "is_active": "on",
                "images-TOTAL_FORMS": "0",
                "images-INITIAL_FORMS": "0",
                "images-MIN_NUM_FORMS": "0",
                "images-MAX_NUM_FORMS": "1000",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        product = Product.objects.get(sku="AI-SKU-1")
        self.assertEqual(product.stock_quantity, 30)
        self.assertEqual(
            list(product.size_inventory.order_by("size").values_list("size", "quantity")),
            [("L", 10), ("M", 10), ("S", 10)],
        )
        self.assertEqual(product.ai_drafts.count(), 1)

    @override_settings(
        DEBUG=True,
        MEDIA_ROOT=tempfile.gettempdir(),
        AI_IMAGE_GENERATOR_ENDPOINT="https://example.com/generate",
        AI_IMAGE_GENERATOR_SHOTS_PER_REQUEST=1,
    )
    @patch("store.ai_enrichment._store_generated_candidate_images")
    @patch("store.ai_enrichment._post_generator_payload")
    def test_external_generator_sends_one_shot_per_request(self, post_generator_payload_mock, store_generated_mock):
        draft = self._create_ai_draft()
        post_generator_payload_mock.side_effect = [
            {"images": [{"image_base64": "Zm9v", "shot_name": "Studio White Hero"}]},
            {"images": [{"image_base64": "YmFy", "shot_name": "Soft Editorial Portrait"}]},
        ]
        store_generated_mock.return_value = ["stored"]

        created = ai_enrichment._call_external_generator(draft, base_url="https://example.com")

        self.assertEqual(created, ["stored"])
        self.assertEqual(post_generator_payload_mock.call_count, 2)
        first_payload = post_generator_payload_mock.call_args_list[0].args[1]
        second_payload = post_generator_payload_mock.call_args_list[1].args[1]
        self.assertEqual(len(first_payload["shots"]), 1)
        self.assertEqual(len(second_payload["shots"]), 1)
        self.assertEqual(first_payload["shots"][0]["name"], "Studio White Hero")
        self.assertEqual(second_payload["shots"][0]["name"], "Soft Editorial Portrait")

    @override_settings(
        DEBUG=True,
        MEDIA_ROOT=tempfile.gettempdir(),
        AI_IMAGE_GENERATOR_ENDPOINT="https://example.com/generate",
        AI_IMAGE_GENERATOR_FALLBACK_TO_LOCAL=True,
    )
    @patch("store.ai_enrichment._generate_local_image_candidates")
    @patch("store.ai_enrichment._call_external_generator")
    def test_timeout_can_fall_back_to_local_candidates(self, call_external_mock, generate_local_mock):
        draft = self._create_ai_draft()
        call_external_mock.side_effect = ai_enrichment.ProductAIError("timeout")
        generate_local_mock.return_value = ["local"]

        created = ai_enrichment.generate_reference_image_candidates(draft, base_url="https://example.com")

        self.assertEqual(created, ["local"])
        generate_local_mock.assert_called_once_with(draft)

    @override_settings(DEBUG=True, MEDIA_ROOT=tempfile.gettempdir())
    def test_ai_image_endpoint_is_retired(self):
        draft = self._create_ai_draft()
        self.client.login(username="0911444555", password="test-pass-123")

        response = self.client.post(
            reverse("store:dashboard-ai-draft-generated-images", args=[draft.id]),
            data=json.dumps(
                {
                    "images": [
                        {
                            "image_base64": "Zm9v",
                            "content_type": "image/jpeg",
                            "shot_name": "Studio White Hero",
                            "prompt": "White background",
                            "aspect_ratio": "4:5",
                        }
                    ]
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 410)
        self.assertEqual(ProductAIDraftImage.objects.filter(draft=draft).count(), 0)

    @override_settings(
        DEBUG=True,
        GEMINI_API_KEY="test-gemini-key",
        MEDIA_ROOT=tempfile.gettempdir(),
        DEFAULT_FILE_STORAGE="django.core.files.storage.FileSystemStorage",
    )
    def test_dashboard_ai_queue_loads(self):
        self.client.login(username="0911444555", password="test-pass-123")

        response = self.client.get(reverse("store:dashboard-ai-queue"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Gemini product queue")
        self.assertContains(response, "Add to queue")

    @override_settings(
        DEBUG=True,
        GEMINI_API_KEY="test-gemini-key",
        MEDIA_ROOT=tempfile.gettempdir(),
        DEFAULT_FILE_STORAGE="django.core.files.storage.FileSystemStorage",
    )
    def test_staff_user_can_queue_ai_draft(self):
        self.client.login(username="0911444555", password="test-pass-123")

        response = self.client.post(
            reverse("store:dashboard-ai-queue"),
            {
                "sku": "QUEUE-1",
                "vendor_hint": "Mercato Studio",
                "price": "249.99",
                "reference_image": self._make_uploaded_image(name="queue-1.jpg", color="purple"),
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        draft = ProductAIDraft.objects.get(sku="QUEUE-1")
        self.assertEqual(draft.pipeline_state, ProductAIDraft.PIPELINE_QUEUED)
        self.assertEqual(draft.status, ProductAIDraft.STATUS_PENDING)
        self.assertContains(response, "QUEUE-1")

    @override_settings(
        DEBUG=True,
        GEMINI_API_KEY="test-gemini-key",
        TASKS_EAGER=True,
        MEDIA_ROOT=tempfile.gettempdir(),
        DEFAULT_FILE_STORAGE="django.core.files.storage.FileSystemStorage",
    )
    @patch("store.services.enrichment.generate_product_ai_payload_for_draft")
    def test_queue_process_endpoint_generates_copy(self, generate_payload_mock):
        draft = ProductAIDraft.objects.create(
            created_by=self.staff_user,
            sku="QUEUE-2",
            vendor_hint="Mercato Studio",
            price=Decimal("349.00"),
            reference_image=self._make_uploaded_image(name="queue-2.jpg", color="purple"),
            status=ProductAIDraft.STATUS_PENDING,
            pipeline_state=ProductAIDraft.PIPELINE_QUEUED,
        )
        generate_payload_mock.return_value = self._mock_ai_result(title="Queued Abaya")
        self.client.login(username="0911444555", password="test-pass-123")

        response = self.client.post(reverse("store:dashboard-ai-draft-process", args=[draft.id]))

        self.assertEqual(response.status_code, 200)
        draft.refresh_from_db()
        self.assertEqual(draft.pipeline_state, ProductAIDraft.PIPELINE_READY)
        self.assertEqual(draft.status, ProductAIDraft.STATUS_SUCCEEDED)
        self.assertEqual(response.json()["ok"], True)
        self.assertEqual(response.json()["draft"]["title"], "Queued Abaya")

        # The ready draft became an unpublished product with a one-click publish URL.
        product = Product.objects.get(sku="QUEUE-2")
        self.assertFalse(product.is_active)
        self.assertEqual(response.json()["draft"]["product_id"], product.id)
        self.assertIn("/publish/", response.json()["draft"]["publish_url"])

    @override_settings(DEBUG=True)
    def test_categories_and_brands_pages_are_paginated(self):
        for index in range(1, 28):
            Category.objects.create(
                title=f"Category {index}",
                slug=f"category-{index}",
                is_active=True,
                is_featured=False,
            )
            Brand.objects.create(
                title=f"Brand {index}",
                slug=f"brand-{index}",
                is_active=True,
                is_featured=False,
            )

        categories_response = self.client.get(reverse("store:all-categories"))
        brands_response = self.client.get(reverse("store:all-brands"))

        self.assertEqual(categories_response.status_code, 200)
        self.assertEqual(brands_response.status_code, 200)
        self.assertContains(categories_response, "Page 1 of")
        self.assertContains(brands_response, "Page 1 of")

    def test_customer_orders_page_is_paginated(self):
        self.client.login(username="0911000000", password="test-pass-123")
        for index in range(13):
            Order.objects.create(
                user=self.user,
                product=self.product,
                quantity=1,
                size="M",
                price_at_purchase=Decimal("100.00"),
                line_total=Decimal("100.00"),
            )

        response = self.client.get(reverse("store:orders"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Page 1 of 2")

    @override_settings(
        DEBUG=True,
        GEMINI_API_KEY="test-gemini-key",
        TASKS_EAGER=True,
        MEDIA_ROOT=tempfile.gettempdir(),
        DEFAULT_FILE_STORAGE="django.core.files.storage.FileSystemStorage",
    )
    @patch("store.services.enrichment.generate_product_ai_payload_for_draft")
    def test_queue_process_endpoint_marks_manual_review_on_failure(self, generate_payload_mock):
        draft = ProductAIDraft.objects.create(
            created_by=self.staff_user,
            sku="QUEUE-3",
            vendor_hint="Mercato Studio",
            price=Decimal("349.00"),
            reference_image=self._make_uploaded_image(name="queue-3.jpg", color="purple"),
            status=ProductAIDraft.STATUS_PENDING,
            pipeline_state=ProductAIDraft.PIPELINE_QUEUED,
        )
        generate_payload_mock.side_effect = ai_enrichment.ProductAIError("Gemini failed")
        self.client.login(username="0911444555", password="test-pass-123")

        response = self.client.post(reverse("store:dashboard-ai-draft-process", args=[draft.id]))

        self.assertEqual(response.status_code, 200)
        draft.refresh_from_db()
        self.assertEqual(draft.pipeline_state, ProductAIDraft.PIPELINE_MANUAL_REVIEW)
        self.assertEqual(draft.status, ProductAIDraft.STATUS_FAILED)
        self.assertEqual(response.json()["ok"], False)

    @override_settings(
        DEBUG=True,
        GEMINI_API_KEY="test-gemini-key",
        MEDIA_ROOT=tempfile.gettempdir(),
        DEFAULT_FILE_STORAGE="django.core.files.storage.FileSystemStorage",
    )
    def test_manual_review_endpoint_marks_draft(self):
        draft = ProductAIDraft.objects.create(
            created_by=self.staff_user,
            sku="QUEUE-4",
            vendor_hint="Mercato Studio",
            price=Decimal("349.00"),
            reference_image=self._make_uploaded_image(name="queue-4.jpg", color="purple"),
            status=ProductAIDraft.STATUS_PENDING,
            pipeline_state=ProductAIDraft.PIPELINE_QUEUED,
        )
        self.client.login(username="0911444555", password="test-pass-123")

        response = self.client.post(
            reverse("store:dashboard-ai-draft-manual-review", args=[draft.id]),
        )

        self.assertEqual(response.status_code, 200)
        draft.refresh_from_db()
        self.assertEqual(draft.pipeline_state, ProductAIDraft.PIPELINE_MANUAL_REVIEW)
        self.assertEqual(response.json()["ok"], True)


def _make_catalog(prefix="Guard"):
    """Category/brand/product fixture shared by the focused test classes."""
    category = Category.objects.create(
        title=f"{prefix} Category",
        slug=f"{prefix.lower()}-category",
        is_active=True,
        is_featured=True,
    )
    brand = Brand.objects.create(
        title=f"{prefix} Brand",
        slug=f"{prefix.lower()}-brand",
        is_active=True,
        is_featured=True,
    )
    product = Product.objects.create(
        title=f"{prefix} Ring",
        slug=f"{prefix.lower()}-ring",
        sku=f"SKU-{prefix.upper()}-1",
        short_description="A ring",
        product_image="product/test.jpg",
        price=Decimal("100.00"),
        category=category,
        brand=brand,
        is_active=True,
        is_featured=True,
        is_sold_out=False,
    )
    set_product_sizes(product, ["S", "M", "L"])
    return category, brand, product


class BackgroundTaskQueueTests(TestCase):
    def setUp(self):
        self.category, self.brand, self.product = _make_catalog("Queue")
        self.user = User.objects.create_user(username="0911600000", password="test-pass-123")
        Address.objects.create(user=self.user, address="Bole Atlas", city="Addis Ababa", phone="0911600000")
        # Product creation above already enqueued an autopublish task; start clean.
        BackgroundTask.objects.all().delete()

    @override_settings(TASKS_EAGER=False)
    def test_enqueue_creates_pending_row(self):
        task = task_queue.enqueue(
            BackgroundTask.TYPE_TELEGRAM_PRODUCT_POST,
            {"product_id": self.product.id},
        )
        task.refresh_from_db()
        self.assertEqual(task.status, BackgroundTask.STATUS_PENDING)
        self.assertEqual(task.attempts, 0)

    @override_settings(TASKS_EAGER=False)
    def test_run_pending_executes_due_tasks(self):
        task_queue.enqueue(BackgroundTask.TYPE_TELEGRAM_PRODUCT_POST, {"product_id": self.product.id})
        processed = task_queue.run_pending()
        self.assertEqual(processed, 1)
        task = BackgroundTask.objects.get()
        # No Telegram credentials in tests -> handler is a silent no-op.
        self.assertEqual(task.status, BackgroundTask.STATUS_DONE)

    @override_settings(TASKS_EAGER=False)
    @patch("store.services.telegram.send_product_post", side_effect=RuntimeError("boom"))
    def test_failing_handler_retries_with_backoff_then_fails(self, send_mock):
        task = task_queue.enqueue(BackgroundTask.TYPE_TELEGRAM_PRODUCT_POST, {"product_id": self.product.id})
        for attempt in range(1, task_queue.MAX_ATTEMPTS + 1):
            task_queue.execute(task)
            task.refresh_from_db()
            self.assertEqual(task.attempts, attempt)
            self.assertIn("boom", task.last_error)
            if attempt < task_queue.MAX_ATTEMPTS:
                self.assertEqual(task.status, BackgroundTask.STATUS_PENDING)
            else:
                self.assertEqual(task.status, BackgroundTask.STATUS_FAILED)

        # A staff retry re-queues the task for a fresh round of attempts.
        task_queue.retry_task(task)
        task.refresh_from_db()
        self.assertEqual(task.status, BackgroundTask.STATUS_PENDING)
        self.assertEqual(task.attempts, 0)

    def test_checkout_enqueues_order_notification_after_commit(self):
        Cart.objects.create(user=self.user, product=self.product, quantity=1, size="M")
        self.client.login(username="0911600000", password="test-pass-123")

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("store:checkout"))

        self.assertEqual(response.status_code, 302)
        task = BackgroundTask.objects.get(task_type=BackgroundTask.TYPE_TELEGRAM_ORDER_NOTIFY)
        self.assertEqual(task.payload["user_id"], self.user.id)
        self.assertEqual(task.payload["order_count"], 1)

    def test_suspension_skips_product_post_enqueue(self):
        BackgroundTask.objects.all().delete()
        with suspend_telegram_autopublish():
            self.product.save()
        self.assertFalse(
            BackgroundTask.objects.filter(task_type=BackgroundTask.TYPE_TELEGRAM_PRODUCT_POST).exists()
        )

        self.product.save()
        self.assertTrue(
            BackgroundTask.objects.filter(task_type=BackgroundTask.TYPE_TELEGRAM_PRODUCT_POST).exists()
        )


class GuestCheckoutTests(TestCase):
    def setUp(self):
        self.category, self.brand, self.product = _make_catalog("Guest")

    def test_guest_checkout_creates_no_auth_user_row(self):
        users_before = User.objects.count()

        add_response = self.client.post(
            reverse("store:add-to-cart"), {"prod_id": self.product.id, "size": "M"}
        )
        self.assertEqual(add_response.status_code, 302)
        session_key = self.client.session.session_key
        self.assertEqual(Cart.objects.filter(user=None, session_key=session_key).count(), 1)

        with self.captureOnCommitCallbacks(execute=True):
            checkout_response = self.client.post(
                reverse("store:checkout"),
                {
                    "full_name": "Guest Buyer",
                    "phone": "0911000111",
                    "city": "Addis Ababa",
                    "address": "Bole Atlas street 12",
                },
            )

        self.assertEqual(checkout_response.status_code, 302)
        self.assertEqual(User.objects.count(), users_before)

        order = Order.objects.get(session_key=session_key)
        self.assertIsNone(order.user)
        self.assertEqual(order.guest_contact["full_name"], "Guest Buyer")
        self.assertEqual(order.customer_name, "Guest Buyer")
        self.assertEqual(Cart.objects.filter(session_key=session_key).count(), 0)

        notify_task = BackgroundTask.objects.get(task_type=BackgroundTask.TYPE_TELEGRAM_ORDER_NOTIFY)
        self.assertIsNone(notify_task.payload["user_id"])
        self.assertEqual(notify_task.payload["guest_contact"]["phone"], "0911000111")

    def test_guest_carts_are_isolated_per_session(self):
        first = self.client
        first.post(reverse("store:add-to-cart"), {"prod_id": self.product.id, "size": "M"})

        from django.test import Client as TestClient

        second = TestClient()
        response = second.get(reverse("store:cart"))
        self.assertContains(response, "Your cart is empty")


class HtmxInteractionTests(TestCase):
    def setUp(self):
        self.category, self.brand, self.product = _make_catalog("Htmx")
        self.user = User.objects.create_user(username="0911700000", password="test-pass-123")

    def test_add_to_cart_returns_feedback_partial_with_badge(self):
        response = self.client.post(
            reverse("store:add-to-cart"),
            {"prod_id": self.product.id, "size": "M"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "zent-alert--success")
        self.assertContains(response, 'id="cart-count-desktop"')
        self.assertContains(response, "hx-swap-oob")

    def test_plus_cart_returns_full_cart_contents(self):
        self.client.login(username="0911700000", password="test-pass-123")
        item = Cart.objects.create(user=self.user, product=self.product, quantity=1, size="M")

        response = self.client.post(
            reverse("store:plus-cart", args=[item.id]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="cart-contents"')
        self.assertContains(response, '<span class="spring-cart-qty-display">2</span>', html=False)
        item.refresh_from_db()
        self.assertEqual(item.quantity, 2)

    def test_wishlist_toggle_swaps_button_partial(self):
        self.client.login(username="0911700000", password="test-pass-123")

        response = self.client.post(
            reverse("store:toggle-wishlist", args=[self.product.id]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "is-saved")
        self.assertTrue(Wishlist.objects.filter(user=self.user, product=self.product).exists())

        response = self.client.post(
            reverse("store:toggle-wishlist", args=[self.product.id]),
            HTTP_HX_REQUEST="true",
        )
        self.assertNotContains(response, "is-saved")
        self.assertFalse(Wishlist.objects.filter(user=self.user, product=self.product).exists())


class QueryCountGuardTests(TestCase):
    """Lock in the P3 query-count wins so regressions fail loudly.

    If one of these numbers changes, check `CaptureQueriesContext` output
    before bumping it — an accidental N+1 in the card grid shows up here.
    """

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.category, self.brand, self.product = _make_catalog("Qc")
        for index in range(6):
            extra = Product.objects.create(
                title=f"Qc Extra {index}",
                slug=f"qc-extra-{index}",
                sku=f"SKU-QC-EXTRA-{index}",
                short_description="Extra",
                product_image="product/test.jpg",
                price=Decimal("50.00"),
                category=self.category,
                brand=self.brand,
                is_active=True,
                is_featured=False,
                is_sold_out=False,
            )
            set_product_sizes(extra, ["S", "M"])

    def test_detail_view_query_count(self):
        url = reverse("store:product-detail", args=[self.product.slug])
        self.client.get(url)  # warm menu caches + session
        with self.assertNumQueries(13):
            self.client.get(url)

    def test_collection_view_query_count_anonymous(self):
        url = reverse("store:all-products")
        self.client.get(url)  # warm menu/meta/fragment caches
        with self.assertNumQueries(1):
            # Fragment-cached grid: only the paginator count remains.
            self.client.get(url)

    def test_cart_view_query_count(self):
        user = User.objects.create_user(username="0911800000", password="test-pass-123")
        Cart.objects.create(user=user, product=self.product, quantity=1, size="M")
        self.client.login(username="0911800000", password="test-pass-123")
        self.client.get(reverse("store:cart"))  # warm caches
        with self.assertNumQueries(7):
            self.client.get(reverse("store:cart"))


@override_settings(
    DEBUG=True,
    MEDIA_ROOT=tempfile.gettempdir(),
    DEFAULT_FILE_STORAGE="django.core.files.storage.FileSystemStorage",
)
class AIDraftAutomationTests(TestCase):
    """Conservative taxonomy resolution + automatic product creation from drafts."""

    def setUp(self):
        self.staff_user = User.objects.create_user(
            username="0911700000", password="test-pass-123", is_staff=True
        )
        self.category = Category.objects.create(
            title="Dresses", slug="dresses", is_active=True, is_featured=False
        )
        self.brand = Brand.objects.create(
            title="Zentanee Basics", slug="zentanee-basics", is_active=True, is_featured=False
        )
        BackgroundTask.objects.all().delete()

    def _image(self, name="ref.jpg", color="navy"):
        image_bytes = BytesIO()
        Image.new("RGB", (40, 40), color=color).save(image_bytes, format="JPEG")
        image_bytes.seek(0)
        return SimpleUploadedFile(name, image_bytes.read(), content_type="image/jpeg")

    def _payload(
        self,
        *,
        title="Flowy Evening Dress",
        collection_slug="dresses",
        collection_proposal=None,
        collection_confidence="high",
        brand_slug=None,
        brand_proposal=None,
        brand_confidence="low",
    ):
        return {
            "catalog_fields": {
                "title": title,
                "slug_hint": "flowy-evening-dress",
                "short_description": "A flowing evening dress with soft drape.",
                "detail_description": "Full-length dress in a breathable fabric.",
                "material": "Chiffon",
                "color": "Emerald",
                "fit_notes": "Relaxed fit.",
                "care_notes": "Hand wash cold.",
                "suggested_category": "",
                "suggested_brand": "",
                "product_type": "Dress",
            },
            "classification": {
                "collection": {
                    "matched_slug": collection_slug,
                    "proposed_new_title": collection_proposal,
                    "confidence": collection_confidence,
                    "reason": "test",
                },
                "brand": {
                    "matched_slug": brand_slug,
                    "proposed_new_title": brand_proposal,
                    "confidence": brand_confidence,
                    "reason": "test",
                },
            },
            "seo": {
                "seo_title": "Flowy Evening Dress | Zentanee",
                "meta_description": "A flowing evening dress.",
                "image_alt_text": "Flowy evening dress",
            },
            "confidence": {"overall": "high", "reasoning_notes": [], "needs_manual_review": []},
        }

    def _draft(self, sku="AI-AUTO-1", payload=None, **kwargs):
        defaults = dict(
            created_by=self.staff_user,
            sku=sku,
            price=Decimal("199.00"),
            reference_image=self._image(name=f"{sku}-ref.jpg"),
            status=ProductAIDraft.STATUS_SUCCEEDED,
            pipeline_state=ProductAIDraft.PIPELINE_READY,
            response_payload=payload if payload is not None else self._payload(),
        )
        defaults.update(kwargs)
        return ProductAIDraft.objects.create(**defaults)

    def test_matched_slug_assigns_existing_collection(self):
        from store.services.enrichment import create_product_from_draft

        draft = self._draft()
        product, created, notes = create_product_from_draft(draft)

        self.assertTrue(created)
        self.assertFalse(product.is_active)
        self.assertEqual(product.category, self.category)
        self.assertIsNone(product.brand)
        self.assertEqual(Category.objects.count(), 1)
        draft.refresh_from_db()
        self.assertEqual(draft.product_id, product.id)

    def test_no_confident_match_does_not_create_collection(self):
        from store.services.enrichment import create_product_from_draft

        draft = self._draft(
            sku="AI-AUTO-2",
            payload=self._payload(
                collection_slug=None,
                collection_proposal="Evening Gowns",
                collection_confidence="medium",
            ),
        )
        product, created, notes = create_product_from_draft(draft)

        self.assertIsNone(product)
        self.assertFalse(created)
        self.assertEqual(Category.objects.count(), 1)
        self.assertTrue(any("collection" in note.lower() for note in notes))

    def test_high_confidence_proposal_creates_collection_once(self):
        from store.services.enrichment import create_product_from_draft

        first = self._draft(
            sku="AI-AUTO-3",
            payload=self._payload(
                collection_slug=None,
                collection_proposal="Handbags",
                collection_confidence="high",
            ),
        )
        product, created, notes = create_product_from_draft(first)
        self.assertTrue(created)
        handbags = Category.objects.get(slug="handbags")
        self.assertTrue(handbags.is_active)
        self.assertEqual(product.category, handbags)

        # A second draft proposing the same collection reuses it instead of duplicating.
        second = self._draft(
            sku="AI-AUTO-4",
            payload=self._payload(
                collection_slug=None,
                collection_proposal="Handbags",
                collection_confidence="high",
            ),
        )
        second_product, second_created, _ = create_product_from_draft(second)
        self.assertTrue(second_created)
        self.assertEqual(second_product.category, handbags)
        self.assertEqual(Category.objects.filter(title__iexact="handbags").count(), 1)

    def test_brand_guess_without_high_confidence_stays_empty(self):
        from store.services.enrichment import create_product_from_draft

        draft = self._draft(
            sku="AI-AUTO-5",
            payload=self._payload(brand_proposal="Guchy", brand_confidence="medium"),
        )
        product, created, _ = create_product_from_draft(draft)

        self.assertTrue(created)
        self.assertIsNone(product.brand)
        self.assertEqual(Brand.objects.count(), 1)

    def test_high_confidence_brand_proposal_creates_brand(self):
        from store.services.enrichment import create_product_from_draft

        draft = self._draft(
            sku="AI-AUTO-6",
            payload=self._payload(brand_proposal="Mercato Studio", brand_confidence="high"),
        )
        product, created, _ = create_product_from_draft(draft)

        self.assertTrue(created)
        self.assertEqual(product.brand.title, "Mercato Studio")
        self.assertTrue(product.brand.is_active)

    def test_cover_and_gallery_uploads_are_copied_to_product(self):
        from store.models import ProductImages
        from store.services.enrichment import create_product_from_draft

        draft = self._draft(sku="AI-AUTO-7", cover_image=self._image(name="cover-shot.jpg", color="black"))
        draft.gallery_uploads.create(image=self._image(name="gallery-1.jpg", color="red"), sort_order=1)
        draft.gallery_uploads.create(image=self._image(name="gallery-2.jpg", color="green"), sort_order=2)

        product, created, _ = create_product_from_draft(draft)

        self.assertTrue(created)
        self.assertIn("cover-shot", product.product_image.name)
        self.assertEqual(ProductImages.objects.filter(product=product).count(), 2)

    def test_existing_sku_blocks_product_creation(self):
        from store.services.enrichment import create_product_from_draft

        Product.objects.create(
            title="Existing",
            slug="existing",
            sku="AI-AUTO-8",
            short_description="Existing product",
            product_image="product/test.jpg",
            price=Decimal("50.00"),
            category=self.category,
            is_active=True,
            is_featured=False,
            is_sold_out=False,
        )
        draft = self._draft(sku="AI-AUTO-8")

        product, created, notes = create_product_from_draft(draft)

        self.assertIsNone(product)
        self.assertFalse(created)
        self.assertTrue(any("already exists" in note for note in notes))

    @override_settings(TASKS_EAGER=False)
    def test_publish_endpoint_activates_product_and_queues_telegram_post(self):
        from store.services.enrichment import create_product_from_draft

        draft = self._draft(sku="AI-AUTO-9")
        product, _, _ = create_product_from_draft(draft)
        BackgroundTask.objects.all().delete()
        self.client.login(username="0911700000", password="test-pass-123")

        response = self.client.post(reverse("store:dashboard-ai-draft-publish", args=[draft.id]))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        product.refresh_from_db()
        self.assertTrue(product.is_active)
        task = BackgroundTask.objects.get(task_type=BackgroundTask.TYPE_TELEGRAM_PRODUCT_POST)
        self.assertEqual(task.payload["product_id"], product.id)
        self.assertTrue(task.payload["force"])

    def test_publish_endpoint_requires_created_product(self):
        draft = self._draft(sku="AI-AUTO-10", pipeline_state=ProductAIDraft.PIPELINE_QUEUED, response_payload={})
        self.client.login(username="0911700000", password="test-pass-123")

        response = self.client.post(reverse("store:dashboard-ai-draft-publish", args=[draft.id]))

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])

    @override_settings(
        STORE_DELIVERY_NOTE="Test delivery promise.",
        STORE_RETURN_NOTE="Check the item with the driver present - on-the-spot returns only.",
    )
    def test_detail_page_falls_back_to_store_policy_notes(self):
        product = Product.objects.create(
            title="Policy Dress",
            slug="policy-dress",
            sku="POLICY-1",
            short_description="A dress",
            product_image="product/test.jpg",
            price=Decimal("120.00"),
            category=self.category,
            is_active=True,
            is_featured=False,
            is_sold_out=False,
        )

        response = self.client.get(reverse("store:product-detail", args=[product.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test delivery promise.")
        self.assertContains(response, "on-the-spot returns only")

    def test_draft_initial_carries_no_policy_fields(self):
        draft = self._draft(sku="AI-AUTO-11")
        initial = ai_enrichment.draft_to_product_initial(
            draft, categories=[self.category], brands=[self.brand]
        )

        self.assertNotIn("delivery_note", initial)
        self.assertNotIn("return_note", initial)
        self.assertEqual(initial["category"], self.category.pk)

