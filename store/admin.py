from django.contrib import admin
from django.contrib import messages
from django.conf import settings
from django.db.models import OuterRef, Subquery
from django.utils import timezone
from django.utils.html import format_html
from django.utils.http import urlencode
from .models import Address, Category, Product, Cart, Order, ProductImages, ProductSizeStock, Brand, Coupon, AffiliateProfile, AffiliateClick, AffiliateCommission, TelegramBotOrder, Wishlist, ProductReview, RestockRequest
from .telegram_notify import notify_customer_delivery_status, post_product_to_channel, suspend_telegram_autopublish

# Register your models here.
class AddressAdmin(admin.ModelAdmin):
    list_display = ('user', 'address', 'city', 'phone')
    list_filter = ('city', 'phone')
    list_per_page = 10
    search_fields = ('address', 'city', 'phone')


class CategoryAdmin(admin.ModelAdmin):
    list_display = ('title', 'slug', 'category_image', 'is_active', 'is_featured', 'updated_at')
    list_editable = ('slug', 'is_active', 'is_featured')
    list_filter = ('is_active', 'is_featured')
    list_per_page = 10
    search_fields = ('title', 'description')
    prepopulated_fields = {"slug": ("title", )}

class BrandAdmin(admin.ModelAdmin):
    list_display = ('title', 'slug', 'brand_image', 'is_active', 'is_featured', 'updated_at')
    list_editable = ('slug', 'is_active', 'is_featured')
    list_filter = ('is_active', 'is_featured')
    list_per_page = 10
    search_fields = ('title', 'description')
    prepopulated_fields = {"slug": ("title", )}

class ProductImagesAdmin(admin.TabularInline):
    model = ProductImages


class ProductSizeStockAdmin(admin.TabularInline):
    model = ProductSizeStock
    extra = 1

class ProductAdmin(admin.ModelAdmin):
    inlines = [ProductImagesAdmin, ProductSizeStockAdmin]
    
    list_display = ('title', 'is_sold_out', 'stock_quantity', 'slug', 'category','brand', 'available_sizes', 'product_image', 'is_active', 'is_featured', 'telegram_channel_last_posted_at', 'updated_at')
    list_editable = ('slug', 'category','brand', 'available_sizes', 'stock_quantity', 'is_sold_out', 'is_active', 'is_featured')
    list_filter = ('category','brand', 'is_sold_out', 'is_active', 'is_featured')
    list_per_page = 10
    search_fields = ('title', 'category', 'short_description')
    prepopulated_fields = {"slug": ("title", )}
    readonly_fields = ("affiliate_link_pattern",)
    actions = ("post_selected_to_telegram",)
    fieldsets = (
        ("Core", {
            "fields": (
                "title",
                "slug",
                "sku",
                "short_description",
                "detail_description",
                "product_image",
                "price",
                "category",
                "brand",
            )
        }),
        ("Product details", {
            "fields": (
                "available_sizes",
                "stock_quantity",
                "material",
                "color",
                "fit_notes",
                "care_notes",
                "delivery_note",
                "return_note",
            )
        }),
        ("Status", {
            "fields": (
                "is_sold_out",
                "is_active",
                "is_featured",
                "affiliate_link_pattern",
                "telegram_channel_last_posted_at",
            )
        }),
    )

    def affiliate_link_pattern(self, obj):
        if not obj:
            return "Save product to generate affiliate link pattern."
        next_path = f"/product/{obj.slug}/"
        relative_link = f"/ref/{{affiliate_code}}/?{urlencode({'next': next_path})}"
        site_url = getattr(settings, "SITE_URL", "").rstrip("/")
        if site_url:
            absolute_link = f"{site_url}{relative_link}"
            return format_html(
                "Relative: <code>{}</code><br>Absolute: <code>{}</code>",
                relative_link,
                absolute_link,
            )
        return format_html("Relative: <code>{}</code>", relative_link)

    affiliate_link_pattern.short_description = "Affiliate link pattern"

    @admin.action(description="Post selected products to Telegram now")
    def post_selected_to_telegram(self, request, queryset):
        posted_count = 0
        skipped_count = 0

        for product in queryset.select_related("category", "brand"):
            if not product.is_active or product.is_sold_out:
                skipped_count += 1
                continue
            if post_product_to_channel(product, force=True):
                posted_count += 1
            else:
                skipped_count += 1

        if posted_count:
            self.message_user(
                request,
                f"{posted_count} product(s) were posted to Telegram.",
                level=messages.SUCCESS,
            )
        if skipped_count:
            self.message_user(
                request,
                f"{skipped_count} product(s) could not be posted. Check product availability and Telegram/media configuration.",
                level=messages.WARNING,
            )

    def _queue_product_post(self, request, product):
        request._telegram_product_post_id = None
        if product and product.pk and product.is_active and not product.is_sold_out:
            request._telegram_product_post_id = product.pk

    def _post_product_after_admin_save(self, request):
        product_id = getattr(request, "_telegram_product_post_id", None)
        request._telegram_product_post_id = None
        if not product_id:
            return

        product = Product.objects.filter(pk=product_id).select_related("category", "brand").first()
        if not product or not product.is_active or product.is_sold_out:
            return

        posted = post_product_to_channel(product, force=True)
        if posted:
            self.message_user(
                request,
                "Telegram channel post sent for this product.",
                level=messages.SUCCESS,
            )
        else:
            self.message_user(
                request,
                "Product was saved, but Telegram channel posting failed. Check Telegram/media configuration.",
                level=messages.WARNING,
            )

    def save_model(self, request, obj, form, change):
        with suspend_telegram_autopublish():
            super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        with suspend_telegram_autopublish():
            super().save_related(request, form, formsets, change)
        self._queue_product_post(request, form.instance)

    def response_add(self, request, obj, post_url_continue=None):
        self._post_product_after_admin_save(request)
        return super().response_add(request, obj, post_url_continue=post_url_continue)

    def response_change(self, request, obj):
        self._post_product_after_admin_save(request)
        return super().response_change(request, obj)

class CartAdmin(admin.ModelAdmin):
    list_display = ('user', 'product', 'size', 'quantity', 'coupon', 'created_at')
    list_editable = ('quantity', 'size', 'coupon')
    list_filter = ('created_at',)
    list_per_page = 20
    search_fields = ('user__username', 'product__title')
    
class CouponAdmin(admin.ModelAdmin):
    list_display = ('code','active', 'discount', 'active_date', 'expiry_date', 'created_date')
    # list_editable = ('code','active', 'discount', 'active_date', 'expiry_date', 'created_date')
    list_per_page = 20

class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'customer_name',
        'customer_username',
        'customer_address',
        'product',
        'size',
        'quantity',
        'price_at_purchase',
        'line_total',
        'status',
        'ordered_date',
    )
    list_editable = ('quantity', 'status', 'size', 'price_at_purchase', 'line_total')
    list_filter = ('status', 'ordered_date')
    list_per_page = 20
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'user__email', 'product__title')

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related('user', 'product')
        latest_address = Address.objects.filter(user=OuterRef('user_id')).order_by('-id')
        return qs.annotate(
            latest_address_text=Subquery(latest_address.values('address')[:1]),
            latest_city_text=Subquery(latest_address.values('city')[:1]),
        )

    @admin.display(description='Name', ordering='user__first_name')
    def customer_name(self, obj):
        full_name = f"{obj.user.first_name} {obj.user.last_name}".strip()
        return full_name or '-'

    @admin.display(description='Username', ordering='user__username')
    def customer_username(self, obj):
        return obj.user.username

    @admin.display(description='Address')
    def customer_address(self, obj):
        address = getattr(obj, 'latest_address_text', '')
        city = getattr(obj, 'latest_city_text', '')
        if address and city:
            return f'{address}, {city}'
        return address or '-'


class AffiliateProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "code", "is_active", "created_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("user__username", "user__email", "code")


class AffiliateClickAdmin(admin.ModelAdmin):
    list_display = ("affiliate", "session_key", "converted", "created_at")
    list_filter = ("converted", "created_at")
    search_fields = ("affiliate__code", "affiliate__user__username", "session_key", "ip_address")


class AffiliateCommissionAdmin(admin.ModelAdmin):
    list_display = ("affiliate", "order", "customer", "rate", "amount", "status", "payout_reference", "paid_at", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("affiliate__code", "affiliate__user__username", "customer__username")
    readonly_fields = ("created_at", "paid_at")
    actions = ("mark_paid_for_delivered_orders", "mark_cancelled")

    @admin.action(description="Mark selected commissions as Paid (Delivered orders only)")
    def mark_paid_for_delivered_orders(self, request, queryset):
        eligible_ids = []
        blocked_count = 0

        for commission in queryset.select_related("order"):
            if commission.status != "Pending":
                blocked_count += 1
                continue

            if not commission.order or commission.order.status != "Delivered":
                blocked_count += 1
                continue

            eligible_ids.append(commission.id)

        updated_count = 0
        if eligible_ids:
            updated_count = AffiliateCommission.objects.filter(id__in=eligible_ids).update(
                status="Paid",
                paid_at=timezone.now(),
            )

        if updated_count:
            self.message_user(request, f"{updated_count} commission(s) marked as Paid.")
        if blocked_count:
            self.message_user(
                request,
                f"{blocked_count} commission(s) skipped because order is not Delivered or status is not Pending.",
                level="warning",
            )

    @admin.action(description="Mark selected commissions as Cancelled")
    def mark_cancelled(self, request, queryset):
        updated_count = queryset.exclude(status="Paid").update(status="Cancelled")
        self.message_user(request, f"{updated_count} commission(s) marked as Cancelled.")


class TelegramBotOrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "customer_full_name",
        "customer_phone",
        "customer_city",
        "product_title",
        "size",
        "quantity",
        "estimated_total",
        "status",
        "created_at",
    )
    list_editable = ("status",)
    list_filter = ("status", "created_at", "customer_city")
    list_per_page = 30
    search_fields = (
        "customer_full_name",
        "customer_phone",
        "customer_city",
        "customer_address",
        "product_title",
        "product_sku",
        "telegram_username",
        "telegram_chat_id",
    )
    readonly_fields = ("created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        previous_status = None
        if change:
            previous_status = TelegramBotOrder.objects.filter(pk=obj.pk).values_list("status", flat=True).first()
        super().save_model(request, obj, form, change)

        if previous_status and previous_status != obj.status:
            delivered = notify_customer_delivery_status(obj)
            if delivered:
                self.message_user(
                    request,
                    f"Customer notified on Telegram: status changed {previous_status} -> {obj.status}.",
                    level=messages.SUCCESS,
                )
            else:
                self.message_user(
                    request,
                    "Status saved but Telegram notification could not be sent.",
                    level=messages.WARNING,
                )
    

class WishlistAdmin(admin.ModelAdmin):
    list_display = ("user", "product", "created_at")
    list_filter = ("created_at",)
    search_fields = ("user__username", "product__title", "product__sku")


class ProductReviewAdmin(admin.ModelAdmin):
    list_display = ("product", "user", "rating", "title", "created_at", "updated_at")
    list_filter = ("rating", "created_at")
    search_fields = ("product__title", "user__username", "title", "comment")


class RestockRequestAdmin(admin.ModelAdmin):
    list_display = ("product", "email", "size", "user", "created_at")
    list_filter = ("created_at",)
    search_fields = ("product__title", "email", "size", "user__username")
    
 

admin.site.register(Address, AddressAdmin)
admin.site.register(Category, CategoryAdmin)
admin.site.register(Brand, BrandAdmin)
admin.site.register(Product, ProductAdmin)
admin.site.register(Coupon, CouponAdmin)
admin.site.register(Cart, CartAdmin)
admin.site.register(Order, OrderAdmin)
admin.site.register(AffiliateProfile, AffiliateProfileAdmin)
admin.site.register(AffiliateClick, AffiliateClickAdmin)
admin.site.register(AffiliateCommission, AffiliateCommissionAdmin)
admin.site.register(TelegramBotOrder, TelegramBotOrderAdmin)
admin.site.register(Wishlist, WishlistAdmin)
admin.site.register(ProductReview, ProductReviewAdmin)
admin.site.register(RestockRequest, RestockRequestAdmin)
