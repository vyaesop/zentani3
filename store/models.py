from django.db import models
from django.contrib.auth.models import User

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

    def __str__(self):
        return self.title
    
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

    def __str__(self):
        return self.title


class Product(models.Model):
    title = models.CharField(max_length=150, verbose_name="Product Title")
    slug = models.SlugField(max_length=160, verbose_name="Product Slug")
    sku = models.CharField(max_length=255, unique=True, verbose_name="Unique Product ID (SKU)")
    short_description = models.TextField(verbose_name="Short Description")
    detail_description = models.TextField(blank=True, null=True, verbose_name="Detail Description")
    product_image = models.ImageField(upload_to='product', verbose_name="Product Image")
    price = models.DecimalField(max_digits=8, decimal_places=2)
    category = models.ForeignKey(Category, verbose_name="Product Categoy", on_delete=models.CASCADE)
    brand = models.ForeignKey(Brand, verbose_name="Product Brand", on_delete=models.CASCADE, default=None, null=True)
    is_active = models.BooleanField(verbose_name="Is Active?")
    is_featured = models.BooleanField(verbose_name="Is Featured?")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created Date")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated Date")

    class Meta:
        verbose_name_plural = 'Products'
        ordering = ('-created_at', )

    def __str__(self):
        return self.title
    
class ProductImages(models.Model):
    image = models.ImageField(upload_to="product-images", default="product.jpg")
    product = models.ForeignKey(Product, related_name="p_images",on_delete=models.SET_NULL, null=True)
    date = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Product images"

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
    quantity = models.PositiveIntegerField(default=1, verbose_name="Quantity")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created Date")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated Date")
 
    def __str__(self):
        return str(self.user)
 
    # Creating Model Property to calculate Quantity x Price
    @property
    def total_price(self):
        if self.coupon:
            discount = self.coupon.discount if self.coupon.discount else 0
            discounted_price = self.product.price - discount
            return self.quantity * discounted_price
        else:
            return self.quantity * self.product.price



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
    quantity = models.PositiveIntegerField(verbose_name="Quantity")
    ordered_date = models.DateTimeField(auto_now_add=True, verbose_name="Ordered Date")
    status = models.CharField(
        choices=STATUS_CHOICES,
        max_length=50,
        default="Pending"
        )


