from django.contrib import admin
from django.conf import settings
from django.utils import timezone
from django.utils.html import format_html
from django.utils.http import urlencode
from .models import Address, Category, Product, Cart, Order, ProductImages, Brand, Coupon, AffiliateProfile, AffiliateClick, AffiliateCommission

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

class ProductAdmin(admin.ModelAdmin):
    inlines = [ProductImagesAdmin]
    
    list_display = ('title', 'is_sold_out', 'slug', 'category','brand', 'available_sizes', 'product_image', 'is_active', 'is_featured', 'updated_at')
    list_editable = ('slug', 'category','brand', 'available_sizes', 'is_sold_out', 'is_active', 'is_featured')
    list_filter = ('category','brand', 'is_sold_out', 'is_active', 'is_featured')
    list_per_page = 10
    search_fields = ('title', 'category', 'short_description')
    prepopulated_fields = {"slug": ("title", )}
    readonly_fields = ("affiliate_link_pattern",)

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
    list_display = ('user', 'product', 'size', 'quantity', 'price_at_purchase', 'line_total', 'status', 'ordered_date')
    list_editable = ('quantity', 'status', 'size', 'price_at_purchase', 'line_total')
    list_filter = ('status', 'ordered_date')
    list_per_page = 20
    search_fields = ('user', 'product')


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