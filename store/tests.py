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
from .models import Address, AffiliateCommission, AffiliateProfile, Brand, Cart, Category, Product, ProductAIDraft, ProductAIDraftImage


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
            available_sizes="S,M,L",
            product_image="product/test.jpg",
            price=Decimal("100.00"),
            category=self.category,
            brand=self.brand,
            is_active=True,
            is_featured=True,
            is_sold_out=False,
        )

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
    def test_uploaded_product_image_is_converted_to_webp(self):
        image_bytes = BytesIO()
        Image.new("RGB", (30, 30), color="red").save(image_bytes, format="JPEG")
        image_bytes.seek(0)

        uploaded = SimpleUploadedFile(
            "test-upload.jpg",
            image_bytes.read(),
            content_type="image/jpeg",
        )

        product = Product.objects.create(
            title="WebP Product",
            slug="webp-product",
            sku="SKU-WEBP-1",
            short_description="Image conversion test",
            available_sizes="",
            product_image=uploaded,
            price=Decimal("150.00"),
            category=self.category,
            brand=self.brand,
            is_active=True,
            is_featured=False,
            is_sold_out=False,
        )

        self.assertTrue(product.product_image.name.lower().endswith(".webp"))

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

    @override_settings(DEBUG=True, GEMINI_API_KEY="test-gemini-key")
    @patch("store.dashboard_views.generate_product_ai_draft")
    def test_staff_user_can_generate_ai_product_draft(self, generate_product_ai_draft_mock):
        generate_product_ai_draft_mock.return_value = {
            "catalog_fields": {
                "title": "Midnight Linen Shirt",
                "slug_hint": "midnight-linen-shirt",
                "short_description": "A crisp shirt drafted from the AI intake flow.",
                "detail_description": "Relaxed linen shirt with a clean front and an elevated finish.",
                "material": "Linen blend",
                "color": "Midnight navy",
                "fit_notes": "Relaxed through the body.",
                "care_notes": "Cold wash and line dry.",
                "delivery_note": "Ships in 2-4 business days.",
                "return_note": "Easy return within 7 days.",
                "suggested_category": "Rings",
                "suggested_brand": "Zent",
                "product_type": "Shirt",
            },
            "confidence": {
                "overall": "medium",
                "reasoning_notes": ["Strong silhouette match from the reference image."],
                "needs_manual_review": ["Confirm fabric composition with the vendor."],
            },
            "sources": [
                {
                    "title": "Vendor match",
                    "url": "https://example.com/vendor-item",
                    "match_type": "exact",
                    "notes": "Matched by SKU.",
                }
            ],
            "search_strategy": {
                "vendor_hint": "Mercato Studio",
                "exact_queries": ["SKU-100"],
                "fallback_queries": ["SKU shirt navy"],
            },
            "image_plan": {
                "reference_preservation_notes": "Keep the garment silhouette unchanged.",
                "negative_prompt": "No extra garments or altered details.",
                "shots": [
                    {
                        "name": "Studio White Hero",
                        "prompt": "Reference-guided studio hero on a clean white background.",
                        "aspect_ratio": "4:5",
                        "priority": 1,
                    }
                ],
            },
        }

        self.client.login(username="0911444555", password="test-pass-123")

        response = self.client.post(
            reverse("store:dashboard-product-create"),
            {
                "sku": "SKU-100",
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

        follow_up = self.client.get(response.url)
        self.assertEqual(follow_up.status_code, 200)
        self.assertContains(follow_up, "Midnight Linen Shirt")
        self.assertContains(follow_up, "Studio White Hero")
        self.assertContains(follow_up, "Mercato Studio")
        self.assertContains(follow_up, "value=\"SKU-100\"", html=False)

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
    def test_staff_user_can_generate_free_ai_image_candidates(self):
        draft = self._create_ai_draft()
        session = self.client.session
        session["dashboard_product_ai_draft_id"] = draft.id
        session.save()
        self.client.login(username="0911444555", password="test-pass-123")

        response = self.client.post(
            reverse("store:dashboard-product-create"),
            {"generate_ai_images": "1"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ProductAIDraftImage.objects.filter(draft=draft).count(), 2)
        self.assertContains(response, "AI image candidates generated")
        self.assertContains(response, "Studio White Hero")

    @override_settings(DEBUG=True, MEDIA_ROOT=tempfile.gettempdir())
    def test_staff_user_can_save_product_with_attached_ai_images(self):
        draft = self._create_ai_draft()
        draft.generated_images.create(
            image=self._make_uploaded_image(name="candidate-1.jpg", color="white"),
            shot_name="Studio White Hero",
            prompt="Primary candidate",
            aspect_ratio="4:5",
            sort_order=1,
        )
        draft.generated_images.create(
            image=self._make_uploaded_image(name="candidate-2.jpg", color="gray"),
            shot_name="Soft Editorial Portrait",
            prompt="Gallery candidate",
            aspect_ratio="4:5",
            sort_order=2,
        )

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
                "available_sizes": "",
                "stock_quantity": "4",
                "price": "349.00",
                "category": str(self.category.id),
                "brand": str(self.brand.id),
                "is_active": "on",
                "images-TOTAL_FORMS": "0",
                "images-INITIAL_FORMS": "0",
                "images-MIN_NUM_FORMS": "0",
                "images-MAX_NUM_FORMS": "1000",
                "sizes-TOTAL_FORMS": "0",
                "sizes-INITIAL_FORMS": "0",
                "sizes-MIN_NUM_FORMS": "0",
                "sizes-MAX_NUM_FORMS": "1000",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        product = Product.objects.get(sku="AI-SKU-1")
        self.assertTrue(product.product_image.name)
        self.assertEqual(product.p_images.count(), 1)
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
    def test_staff_user_can_save_browser_generated_ai_images(self):
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

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ProductAIDraftImage.objects.filter(draft=draft).count(), 1)
