from decimal import Decimal
import uuid
from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.utils import timezone


def _normalize_legacy_media_name(name):
    value = str(name or "").replace("\\", "/").lstrip("/")
    if value.startswith("media/"):
        return value[len("media/"):]
    return value

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
        if self.category_image and getattr(self.category_image, "name", ""):
            self.category_image.name = _normalize_legacy_media_name(self.category_image.name)
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
        if self.brand_image and getattr(self.brand_image, "name", ""):
            self.brand_image.name = _normalize_legacy_media_name(self.brand_image.name)
        super().save(*args, **kwargs)


class Product(models.Model):
    DEFAULT_STOCK_PER_SIZE = 10

    title = models.CharField(max_length=150, verbose_name="Product Title")
    slug = models.SlugField(max_length=160, verbose_name="Product Slug")
    sku = models.CharField(max_length=255, unique=True, verbose_name="Unique Product ID (SKU)")
    short_description = models.TextField(verbose_name="Short Description")
    seo_title = models.CharField(max_length=180, blank=True, verbose_name="SEO Title")
    seo_description = models.CharField(max_length=320, blank=True, verbose_name="SEO Description")
    image_alt_text = models.CharField(max_length=180, blank=True, verbose_name="Image Alt Text")
    detail_description = models.TextField(blank=True, null=True, verbose_name="Detail Description")
    material = models.CharField(max_length=120, blank=True, verbose_name="Material")
    color = models.CharField(max_length=80, blank=True, verbose_name="Color")
    fit_notes = models.TextField(blank=True, verbose_name="Fit Notes")
    care_notes = models.TextField(blank=True, verbose_name="Care Notes")
    delivery_note = models.CharField(max_length=180, blank=True, verbose_name="Delivery Note")
    return_note = models.CharField(max_length=180, blank=True, verbose_name="Return Note")
    stock_quantity = models.PositiveIntegerField(default=0, verbose_name="Stock Quantity")
    product_image = models.ImageField(upload_to='product', verbose_name="Product Image")
    price = models.DecimalField(max_digits=8, decimal_places=2)
    category = models.ForeignKey(Category, verbose_name="Product Categoy", on_delete=models.CASCADE)
    brand = models.ForeignKey(Brand, verbose_name="Product Brand", on_delete=models.CASCADE, default=None, null=True)
    is_active = models.BooleanField(verbose_name="Is Active?")
    is_featured = models.BooleanField(verbose_name="Is Featured?")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created Date")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated Date")
    is_sold_out = models.BooleanField(verbose_name="Is Sold Out?", default=False, null=True)
    telegram_channel_last_post_signature = models.CharField(max_length=64, blank=True, default="")
    telegram_channel_last_posted_at = models.DateTimeField(null=True, blank=True)

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

    @property
    def available_sizes(self):
        """CSV of sizes from ProductSizeStock (read-only compatibility shim).

        Uses .all() so a prefetch_related("size_inventory") on list queries is
        honored. Size mutations go through store.services.inventory.
        """
        from store.constants import size_sort_key

        sizes = [row.size for row in self.size_inventory.all() if row.size and row.size.strip()]
        return ",".join(sorted(sizes, key=size_sort_key))

    def save(self, *args, **kwargs):
        # Inventory sync and sold-out reconciliation are explicit service
        # calls (store.services.inventory) — save() has no side effects.
        if self.product_image and getattr(self.product_image, "name", ""):
            self.product_image.name = _normalize_legacy_media_name(self.product_image.name)
        super().save(*args, **kwargs)

class ProductImages(models.Model):
    image = models.ImageField(upload_to="product-images", default="product.jpg")
    product = models.ForeignKey(Product, related_name="p_images",on_delete=models.SET_NULL, null=True)
    date = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Product images"

    def save(self, *args, **kwargs):
        if self.image and getattr(self.image, "name", ""):
            self.image.name = _normalize_legacy_media_name(self.image.name)
        super().save(*args, **kwargs)


class ProductAIDraft(models.Model):
    STATUS_PENDING = "pending"
    STATUS_SUCCEEDED = "succeeded"
    STATUS_FAILED = "failed"
    PIPELINE_IDLE = "idle"
    PIPELINE_QUEUED = "queued"
    PIPELINE_ANALYZING = "analyzing"
    PIPELINE_GENERATING_IMAGES = "generating_images"
    PIPELINE_READY = "ready"
    PIPELINE_MANUAL_REVIEW = "manual_review"

    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_SUCCEEDED, "Succeeded"),
        (STATUS_FAILED, "Failed"),
    )
    PIPELINE_STATE_CHOICES = (
        (PIPELINE_IDLE, "Idle"),
        (PIPELINE_QUEUED, "Queued"),
        (PIPELINE_ANALYZING, "Generating Copy"),
        (PIPELINE_GENERATING_IMAGES, "Generating Images"),
        (PIPELINE_READY, "Ready"),
        (PIPELINE_MANUAL_REVIEW, "Manual Review"),
    )
    ACTIVE_QUEUE_STATES = (PIPELINE_QUEUED, PIPELINE_ANALYZING, PIPELINE_GENERATING_IMAGES)

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="ai_drafts",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="product_ai_drafts",
    )
    sku = models.CharField(max_length=255, verbose_name="Source SKU")
    vendor_hint = models.CharField(max_length=120, blank=True, verbose_name="Vendor Hint")
    price = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    reference_image = models.ImageField(
        upload_to="ai-reference",
        blank=True,
        null=True,
        verbose_name="Identifier Image",
    )
    secondary_reference_image = models.ImageField(
        upload_to="ai-reference",
        blank=True,
        null=True,
        verbose_name="Secondary Reference Image",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    pipeline_state = models.CharField(max_length=30, choices=PIPELINE_STATE_CHOICES, default=PIPELINE_IDLE)
    error_message = models.CharField(max_length=250, blank=True)
    last_error_stage = models.CharField(max_length=40, blank=True)
    attempt_count = models.PositiveSmallIntegerField(default=0)
    response_payload = models.JSONField(default=dict, blank=True)
    source_links = models.JSONField(default=list, blank=True)
    seo_payload = models.JSONField(default=dict, blank=True)
    image_plan = models.JSONField(default=dict, blank=True)
    generator_payload = models.JSONField(default=dict, blank=True)
    queued_at = models.DateTimeField(null=True, blank=True)
    processing_started_at = models.DateTimeField(null=True, blank=True)
    processing_finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at", "-created_at")
        indexes = [
            models.Index(fields=["created_by", "updated_at"]),
            models.Index(fields=["product", "updated_at"]),
            models.Index(fields=["sku", "updated_at"]),
            models.Index(fields=["status", "updated_at"]),
            models.Index(fields=["created_by", "pipeline_state", "updated_at"]),
        ]

    def __str__(self):
        return f"AI draft {self.sku} ({self.status})"

    def save(self, *args, **kwargs):
        if self.reference_image and getattr(self.reference_image, "name", ""):
            self.reference_image.name = _normalize_legacy_media_name(self.reference_image.name)
        if self.secondary_reference_image and getattr(self.secondary_reference_image, "name", ""):
            self.secondary_reference_image.name = _normalize_legacy_media_name(self.secondary_reference_image.name)
        super().save(*args, **kwargs)

    @property
    def extracted_fields(self):
        return self.response_payload.get("catalog_fields", {})

    @property
    def queue_label(self):
        labels = dict(self.PIPELINE_STATE_CHOICES)
        return labels.get(self.pipeline_state, self.pipeline_state.replace("_", " ").title())


class ProductAIDraftImage(models.Model):
    draft = models.ForeignKey(ProductAIDraft, on_delete=models.CASCADE, related_name="generated_images")
    image = models.ImageField(upload_to="ai-generated", verbose_name="Generated Candidate Image")
    shot_name = models.CharField(max_length=120)
    prompt = models.TextField(blank=True)
    aspect_ratio = models.CharField(max_length=20, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("sort_order", "id")
        indexes = [
            models.Index(fields=["draft", "sort_order"]),
        ]

    def save(self, *args, **kwargs):
        if self.image and getattr(self.image, "name", ""):
            self.image.name = _normalize_legacy_media_name(self.image.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.draft.sku} - {self.shot_name}"


class ProductSizeStock(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="size_inventory")
    size = models.CharField(max_length=50)
    quantity = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("size",)
        constraints = [
            models.UniqueConstraint(fields=["product", "size"], name="unique_product_size_inventory"),
        ]
        indexes = [
            models.Index(fields=["product", "size"]),
        ]

    def __str__(self):
        return f"{self.product.title} - {self.size} ({self.quantity})"


class Wishlist(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="wishlisted_items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="wishlisted_by")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=["user", "product"], name="unique_user_product_wishlist"),
        ]
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["product", "created_at"]),
        ]

    def __str__(self):
        return f"{self.user.username} -> {self.product.title}"


class ProductReview(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="product_reviews")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="reviews")
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    title = models.CharField(max_length=120, blank=True)
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at", "-created_at")
        constraints = [
            models.UniqueConstraint(fields=["user", "product"], name="unique_user_product_review"),
        ]
        indexes = [
            models.Index(fields=["product", "created_at"]),
            models.Index(fields=["user", "created_at"]),
        ]

    def __str__(self):
        return f"{self.product.title} review by {self.user.username}"


class RestockRequest(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="restock_requests")
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="restock_requests")
    email = models.EmailField()
    size = models.CharField(max_length=50, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=["product", "email", "size"], name="unique_restock_interest"),
        ]
        indexes = [
            models.Index(fields=["product", "created_at"]),
            models.Index(fields=["email", "created_at"]),
        ]

    def __str__(self):
        size_label = self.size or "Any size"
        return f"{self.product.title} restock request ({size_label})"

class Coupon(models.Model):
    code = models.CharField(max_length=30, unique=True)
    active = models.BooleanField(default=True)
    discount = models.PositiveIntegerField(help_text='discount in percentage')
    active_date = models.DateField()
    expiry_date = models.DateField()
    created_date = models.DateTimeField(default=timezone.now)
    used_count = models.PositiveIntegerField(default=0, verbose_name="Times Used", editable=False)
    max_uses = models.PositiveIntegerField(null=True, blank=True, verbose_name="Max Uses", help_text="Leave blank for unlimited.")

    def __str__(self) -> str:
        return self.code

    def record_use(self):
        """Increment used_count atomically. Call once per order that applies this coupon."""
        Coupon.objects.filter(pk=self.pk).update(used_count=models.F("used_count") + 1)
        self.used_count += 1

    @property
    def is_exhausted(self):
        return self.max_uses is not None and self.used_count >= self.max_uses
    
class Cart(models.Model):
    # Owned by a user (authenticated) or a session key (guest) — guests no
    # longer get placeholder rows in auth_user.
    user = models.ForeignKey(User, verbose_name="User", on_delete=models.CASCADE, null=True, blank=True)
    session_key = models.CharField(max_length=64, null=True, blank=True, db_index=True, verbose_name="Guest Session Key")
    product = models.ForeignKey(Product, verbose_name="Product", on_delete=models.CASCADE)
    coupon = models.ForeignKey(Coupon, verbose_name="Coupon", on_delete=models.CASCADE, null=True, blank=True)
    size = models.CharField(max_length=50, null=True, blank=True, verbose_name="Size")
    quantity = models.PositiveIntegerField(default=1, verbose_name="Quantity")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created Date")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated Date")

    def __str__(self):
        return str(self.user) if self.user_id else f"guest:{self.session_key}"

    class Meta:
        indexes = [
            models.Index(fields=['user', 'updated_at']),
            models.Index(fields=['user', 'product']),
            models.Index(fields=['session_key', 'updated_at']),
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
    # user is null for guest checkouts; the delivery/contact details captured
    # at checkout live in guest_contact and the session is kept for tracing.
    user = models.ForeignKey(User, verbose_name="User", on_delete=models.CASCADE, null=True, blank=True)
    session_key = models.CharField(max_length=64, blank=True, default="", db_index=True, verbose_name="Guest Session Key")
    guest_contact = models.JSONField(null=True, blank=True, verbose_name="Guest Contact", help_text="full_name/phone/city/address captured at guest checkout")
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
    staff_notes = models.TextField(blank=True, verbose_name="Staff Notes", help_text="Internal notes visible only to staff (address changes, delivery instructions, etc.)")

    class Meta:
        indexes = [
            models.Index(fields=['user', 'ordered_date']),
            models.Index(fields=['product', 'ordered_date']),
            models.Index(fields=['status', 'ordered_date']),
        ]

    @property
    def customer_name(self):
        if self.user_id:
            return self.user.get_full_name() or self.user.username
        if self.guest_contact:
            return self.guest_contact.get("full_name") or "Guest"
        return "Guest"

    @property
    def customer_phone(self):
        if self.guest_contact and self.guest_contact.get("phone"):
            return self.guest_contact["phone"]
        if self.user_id:
            return self.user.username
        return ""

    @property
    def customer_location(self):
        if self.guest_contact:
            parts = [self.guest_contact.get("address", ""), self.guest_contact.get("city", "")]
            return ", ".join(part for part in parts if part)
        if self.user_id:
            latest = self.user.address_set.last()
            if latest:
                return f"{latest.address}, {latest.city}"
        return ""


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


class TelegramBotOrder(models.Model):
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, related_name="telegram_orders")
    product_title = models.CharField(max_length=150)
    product_sku = models.CharField(max_length=255, blank=True)
    size = models.CharField(max_length=50, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    estimated_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    customer_full_name = models.CharField(max_length=150)
    customer_phone = models.CharField(max_length=30)
    customer_city = models.CharField(max_length=150)
    customer_address = models.CharField(max_length=255)

    telegram_chat_id = models.CharField(max_length=40, db_index=True)
    telegram_username = models.CharField(max_length=150, blank=True)

    status = models.CharField(choices=STATUS_CHOICES, max_length=50, default="Pending")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["telegram_chat_id", "created_at"]),
        ]

    def __str__(self):
        return f"TG-{self.id} {self.product_title} ({self.customer_full_name})"


class BackgroundTask(models.Model):
    """Outbox row for work that must not block a user-facing request.

    Drained by `manage.py run_tasks` (always-on hosting) or the
    `POST /internal/run-tasks/` trigger (serverless cron).
    """

    TYPE_TELEGRAM_PRODUCT_POST = "telegram_product_post"
    TYPE_TELEGRAM_ORDER_NOTIFY = "telegram_order_notify"
    TYPE_TELEGRAM_SIGNUP_NOTIFY = "telegram_signup_notify"
    TYPE_AI_ENRICH_DRAFT = "ai_enrich_draft"
    TASK_TYPE_CHOICES = (
        (TYPE_TELEGRAM_PRODUCT_POST, "Telegram product post"),
        (TYPE_TELEGRAM_ORDER_NOTIFY, "Telegram order notification"),
        (TYPE_TELEGRAM_SIGNUP_NOTIFY, "Telegram signup notification"),
        (TYPE_AI_ENRICH_DRAFT, "AI draft enrichment"),
    )

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_DONE = "done"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = (
        (STATUS_PENDING, "Pending"),
        (STATUS_RUNNING, "Running"),
        (STATUS_DONE, "Done"),
        (STATUS_FAILED, "Failed"),
    )

    task_type = models.CharField(max_length=40, choices=TASK_TYPE_CHOICES)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    run_after = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["status", "run_after"]),
            models.Index(fields=["task_type", "status"]),
        ]

    def __str__(self):
        return f"{self.task_type} #{self.pk} ({self.status})"


class TelegramConversationState(models.Model):
    """Persisted state for the multi-step Telegram order conversation.

    The bot runs on serverless/multi-process hosting where an in-memory cache
    is not shared between requests, so the conversation state must live in the
    database to survive between webhook updates.
    """

    chat_id = models.CharField(max_length=40, unique=True, db_index=True)
    state = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Telegram conversation state"
        verbose_name_plural = "Telegram conversation states"

    def __str__(self):
        return f"State for chat {self.chat_id}"
