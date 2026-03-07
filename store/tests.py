from decimal import Decimal
from io import BytesIO
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from .models import Address, AffiliateCommission, AffiliateProfile, Brand, Cart, Category, Product


class StoreFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="0911000000", password="test-pass-123")
        self.other_user = User.objects.create_user(username="0911222333", password="test-pass-123")

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
