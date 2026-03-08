from decimal import Decimal
import uuid
import os
from io import BytesIO
from django.db import models
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile

try:
    from PIL import Image
except ImportError:
    Image = None


def _convert_uploaded_image_to_webp(field_file, quality=80):
    """Return a converted WebP upload for admin/user-uploaded files before storage save."""
    if Image is None or not field_file:
        return None

    # Only process new uploads that are not yet stored.
    if getattr(field_file, "_committed", True):
        return None

    source_file = getattr(field_file, "file", None)
    if source_file is None or not hasattr(source_file, "read"):
        return None

    original_name = field_file.name or getattr(source_file, "name", "upload.jpg")
    original_extension = os.path.splitext(original_name)[1].lower()
    if original_extension == ".webp":
        return None

    try:
        source_file.seek(0)
        image = Image.open(source_file)
        image.load()
    except Exception:
        return None

    if image.mode in ("RGBA", "P"):
        image = image.convert("RGBA")
    else:
        image = image.convert("RGB")

    output = BytesIO()
    image.save(output, format="WEBP", quality=quality, optimize=True)
    output.seek(0)

    webp_name = f"{os.path.splitext(os.path.basename(original_name))[0]}.webp"
    return SimpleUploadedFile(
        webp_name,
        output.read(),
        content_type="image/webp",
    )

# Create your models here.
class Address(models.Model):
    user = models.ForeignKey(User, verbose_name="User", on_delete=models.CASCADE)
    address = models.CharField(max_length=150, verbose_name="Nearest Location")
    city = models.CharField(max_length=150, verbose_name="City")
    phone = models.CharField(max_length=13, verbose_name="phone")

    def __str__(self):
        return self.address


class Category(models.Model):
    title = models.CharField(max_length=50, verbose_name="Category Title")
    slug = models.SlugField(max_length=55, verbose_name="Category Slug")
    description = models.TextField(blank=True, verbose_name="Category Description")
    category_image = models.ImageField(upload_to='category', blank=True, null=True, verbose_name="Category Image")
    is_active = models.BooleanField(verbose_name="Is Active?")
    is_featured = models.BooleanField(verbose_name="Is Featured?")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created Date")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated Date")

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ('-created_at', )
        indexes = [
            models.Index(fields=['is_active', 'is_featured']),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        converted = _convert_uploaded_image_to_webp(self.category_image)
        if converted is not None:
            self.category_image = converted
        super().save(*args, **kwargs)
    
class Brand(models.Model):
    title = models.CharField(max_length=50, verbose_name="Brand Title")
    slug = models.SlugField(max_length=55, verbose_name="Brand Slug")
    description = models.TextField(blank=True, verbose_name="Brand Description")
    brand_image = models.ImageField(upload_to='brand', blank=True, null=True, verbose_name="Brand Image")
    is_active = models.BooleanField(verbose_name="Is Active?")
    is_featured = models.BooleanField(verbose_name="Is Featured?")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created Date")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated Date")

    class Meta:
        verbose_name_plural = 'Brands'
        ordering = ('-created_at', )
        indexes = [
            models.Index(fields=['is_active', 'is_featured']),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        converted = _convert_uploaded_image_to_webp(self.brand_image)
        if converted is not None:
            self.brand_image = converted
        super().save(*args, **kwargs)


class Product(models.Model):
    title = models.CharField(max_length=150, verbose_name="Product Title")
    slug = models.SlugField(max_length=160, verbose_name="Product Slug")
    sku = models.CharField(max_length=255, unique=True, verbose_name="Unique Product ID (SKU)")
    short_description = models.TextField(verbose_name="Short Description")
    available_sizes = models.CharField(max_length=100, blank=True, help_text="Comma-separated list of available sizes (e.g., S,M,L,XL)", verbose_name="Available Sizes")
    detail_description = models.TextField(blank=True, null=True, verbose_name="Detail Description")
    product_image = models.ImageField(upload_to='product', verbose_name="Product Image")
    price = models.DecimalField(max_digits=8, decimal_places=2)
    category = models.ForeignKey(Category, verbose_name="Product Categoy", on_delete=models.CASCADE)
    brand = models.ForeignKey(Brand, verbose_name="Product Brand", on_delete=models.CASCADE, default=None, null=True)
    is_active = models.BooleanField(verbose_name="Is Active?")
    is_featured = models.BooleanField(verbose_name="Is Featured?")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created Date")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated Date")
    is_sold_out = models.BooleanField(verbose_name="Is Sold Out?", default=False, null=True)

    class Meta:
        verbose_name_plural = 'Products'
        ordering = ('-created_at', )
        indexes = [
            models.Index(fields=['is_active', 'is_featured']),
            models.Index(fields=['is_active', 'category']),
            models.Index(fields=['is_active', 'brand']),
            models.Index(fields=['is_active', 'sku']),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        converted = _convert_uploaded_image_to_webp(self.product_image)
        if converted is not None:
            self.product_image = converted
        super().save(*args, **kwargs)
    
class ProductImages(models.Model):
    image = models.ImageField(upload_to="product-images", default="product.jpg")
    product = models.ForeignKey(Product, related_name="p_images",on_delete=models.SET_NULL, null=True)
    date = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Product images"

    def save(self, *args, **kwargs):
        converted = _convert_uploaded_image_to_webp(self.image)
        if converted is not None:
            self.image = converted
        super().save(*args, **kwargs)

class Coupon(models.Model):
    code = models.CharField(max_length=30, unique=True,default=None)
    active = models.BooleanField(default=True)
    discount = models.PositiveBigIntegerField(help_text='discount in percentage',default=None)
    active_date = models.DateField(default=None)
    expiry_date = models.DateField(default=None)
    created_date = models.DateTimeField(default=None)

    
    def __str__(self) -> str:
        return self.code
    
class Cart(models.Model):
    user = models.ForeignKey(User, verbose_name="User", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, verbose_name="Product", on_delete=models.CASCADE)
    coupon = models.ForeignKey(Coupon, verbose_name="Coupon", on_delete=models.CASCADE, null=True, blank=True)
    size = models.CharField(max_length=50, null=True, blank=True, verbose_name="Size")
    quantity = models.PositiveIntegerField(default=1, verbose_name="Quantity")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created Date")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated Date")
 
    def __str__(self):
        return str(self.user)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'updated_at']),
            models.Index(fields=['user', 'product']),
        ]
 
    # Creating Model Property to calculate Quantity x Price
    @property
    def total_price(self):
        base_price_per_item = self.product.price
        effective_price_per_item = base_price_per_item

        if self.coupon and self.coupon.discount is not None and self.coupon.active:
            # Assuming coupon.discount is a percentage
            discount_percentage = Decimal(self.coupon.discount) / Decimal(100)
            discount_amount_per_item = base_price_per_item * discount_percentage
            effective_price_per_item = base_price_per_item - discount_amount_per_item
        return self.quantity * effective_price_per_item



STATUS_CHOICES = (
    ('Pending', 'Pending'),
    ('Accepted', 'Accepted'),
    ('Packed', 'Packed'),
    ('On The Way', 'On The Way'),
    ('Delivered', 'Delivered'),
    ('Cancelled', 'Cancelled')
)

class Order(models.Model):
    user = models.ForeignKey(User, verbose_name="User", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, verbose_name="Product", on_delete=models.CASCADE)
    size = models.CharField(max_length=50, null=True, blank=True, verbose_name="Size")
    quantity = models.PositiveIntegerField(verbose_name="Quantity")
    price_at_purchase = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Price at Purchase")
    line_total = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Line Total")
    ordered_date = models.DateTimeField(auto_now_add=True, verbose_name="Ordered Date")
    status = models.CharField(
        choices=STATUS_CHOICES,
        max_length=50,
        default="Pending"
        )

    class Meta:
        indexes = [
            models.Index(fields=['user', 'ordered_date']),
            models.Index(fields=['product', 'ordered_date']),
            models.Index(fields=['status', 'ordered_date']),
        ]


class AffiliateProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="affiliate_profile")
    code = models.SlugField(max_length=40, unique=True, db_index=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["is_active", "created_at"]),
        ]

    def __str__(self):
        return f"{self.user.username} ({self.code})"

    @staticmethod
    def generate_unique_code(prefix="aff"):
        while True:
            candidate = f"{prefix}-{uuid.uuid4().hex[:10]}"
            if not AffiliateProfile.objects.filter(code=candidate).exists():
                return candidate


class AffiliateClick(models.Model):
    affiliate = models.ForeignKey(AffiliateProfile, on_delete=models.CASCADE, related_name="clicks")
    session_key = models.CharField(max_length=64, blank=True, null=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.CharField(max_length=300, blank=True)
    landing_path = models.CharField(max_length=300, blank=True)
    converted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["affiliate", "created_at"]),
            models.Index(fields=["session_key", "created_at"]),
            models.Index(fields=["converted", "created_at"]),
        ]


COMMISSION_STATUS_CHOICES = (
    ("Pending", "Pending"),
    ("Paid", "Paid"),
    ("Cancelled", "Cancelled"),
)


class AffiliateCommission(models.Model):
    affiliate = models.ForeignKey(AffiliateProfile, on_delete=models.CASCADE, related_name="commissions")
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True, related_name="affiliate_commissions")
    customer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="affiliate_purchases")
    rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("5.00"))
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=COMMISSION_STATUS_CHOICES, default="Pending")
    payout_reference = models.CharField(max_length=120, blank=True)
    payout_note = models.CharField(max_length=250, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["affiliate", "status", "created_at"]),
            models.Index(fields=["order", "created_at"]),
        ]
