import django
from django.core import paginator
from django.core.paginator import Paginator
from django.contrib.auth.models import User
from django.forms import DecimalField
from django.http import HttpResponseRedirect, JsonResponse
from store.models import Address, Cart, Category, Coupon, Order, Product, Brand
from django.shortcuts import redirect, render, get_object_or_404
from .forms import RegistrationForm, AddressForm
from django.contrib import messages
from django.views import View
import decimal
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login # Import the login function
from django.utils.decorators import method_decorator # for Class Based Views
from django.template.loader import render_to_string
from decimal import Decimal
from django.db.models import Sum, F, ExpressionWrapper, DecimalField




# Create your views here.

def home(request):
    categories = Category.objects.filter(is_active=True, is_featured=True).order_by("created_at")[:8]
    brands = Brand.objects.filter(is_active=True, is_featured=True)[:12]

    products = Product.objects.filter(is_active=True, is_featured=True)[:50]
    context = {
        'categories': categories,
        'products': products,
        'brands': brands
    }
    return render(request, 'store/index.html', context)


def detail(request, slug):
    product = get_object_or_404(Product, slug=slug)
    related_products = Product.objects.exclude(id=product.id).filter(is_active=True, category=product.category)[:4]
    p_image = product.p_images.all()
    available_sizes_list = [s.strip() for s in product.available_sizes.split(',') if s.strip()] if product.available_sizes else []
    context = {
        'product': product,
        'related_products': related_products,
        'p_image': p_image,
        'available_sizes': available_sizes_list,
    }
    return render(request, 'store/detail.html', context)



def search_view(request):
    query = request.GET.get("q")
    products = Product.objects.filter(title__icontains="" if query is None else query, is_active=True)
    
    context = {
        'products': products,
        'query' : query,
    }

    return render(request, "store/search.html", context)

def products(request):
    products = Product.objects.filter(is_active=True)
    context = {
        'products': products,
    }
    return render(request, 'store/products.html', context)

def filter_product(request):
    categories = request.GET.getlist("category[]")
 
    min_price = request.GET['min_price']
    max_price = request.GET['max_price']
 
    try:
        min_price = Decimal(min_price)
        max_price = Decimal(max_price)
    except decimal.InvalidOperation:
        return JsonResponse({"error": "Invalid price values"})
 
    products = Product.objects.filter(is_active=True).order_by("-id").distinct()
 
    products = products.filter(price__gte=min_price)
    products = products.filter(price__lte=max_price)
 
    if len(categories) > 0:
        products = products.filter(category__id__in=categories).distinct()
 
    data = render_to_string("store/product-list.html", {"products": products})
    return JsonResponse({"data": data})


def all_categories(request):
    categories = Category.objects.filter(is_active=True)
    return render(request, 'store/categories.html', {'categories':categories})


def all_brands(request):
    brands = Brand.objects.filter(is_active=True)
    return render(request, 'store/brands.html', {'brands':brands})

def category_products(request, slug):
    if slug != None:
        category = get_object_or_404(Category, slug=slug)
        products = Product.objects.filter(is_active=True, category=category).order_by("-sku")
        categories = Category.objects.filter(is_active=True)
        paginator = Paginator(products, 24)
        product_count = products.count()
        page = request.GET.get('page')
        paged_products = paginator.get_page(page)
    else:
        products = Product.objects.all().filter(is_active=True).order_by("-sku")
        categories = Category.objects.filter(is_active=True)
        paginator = Paginator(products, 24)
        product_count = products.count()
        page = request.GET.get('page')
        paged_products = paginator.get_page(page)
    context = {
        'category': category,
        'products': paged_products,
        'categories': categories,
        'paginator': paginator,
        'product_count': product_count
    }
    return render(request, 'store/category_products.html', context)

def brand_products(request, slug):
    if slug != None:
        brand = get_object_or_404(Brand, slug=slug)
        products = Product.objects.filter(is_active=True, brand=brand)
        brands = Brand.objects.filter(is_active=True)
        paginator = Paginator(products, 24)
        product_count = products.count()
        page = request.GET.get('page')
        paged_products = paginator.get_page(page)
    else:
        products = Product.objects.all().filter(is_active=True)
        brands = Brand.objects.filter(is_active=True)
        paginator = Paginator(products, 24)
        product_count = products.count()
        page = request.GET.get('page')
        paged_products = paginator.get_page(page)
    context = {
        'brand': brand,
        'products': paged_products,
        'brands': brands,
        'paginator': paginator,
        'product_count': product_count
    }
    return render(request, 'store/brand_products.html', context)


# Authentication Starts Here

class RegistrationView(View):
    def get(self, request):
        form = RegistrationForm()
        return render(request, 'account/register.html', {'form': form})
    
    def post(self, request):
        form = RegistrationForm(request.POST)
        if form.is_valid():
            messages.success(request, "Congratulations! Registration Successful!")
            user = form.save()
            login(request, user) # Log the user in
            return redirect('store:home')
        return render(request, 'account/register.html', {'form': form})
        

@login_required
def profile(request):
    addresses = Address.objects.filter(user=request.user)
    orders = Order.objects.filter(user=request.user)
    return render(request, 'account/profile.html', {'addresses':addresses, 'orders':orders})


@method_decorator(login_required, name='dispatch')
class AddressView(View):
    def get(self, request):
        form = AddressForm()
        return render(request, 'account/add_address.html', {'form': form})

    def post(self, request):
        form = AddressForm(request.POST)
        if form.is_valid():
            user=request.user
            address = form.cleaned_data['address']
            city = form.cleaned_data['city']
            phone = form.cleaned_data['phone']
            reg = Address(user=user, address=address, city=city, phone=phone)
            reg.save()
            messages.success(request, "New Address Added Successfully.")
        return redirect('store:profile')


@login_required
def remove_address(request, id):
    a = get_object_or_404(Address, user=request.user, id=id)
    a.delete()
    messages.success(request, "Address removed.")
    return redirect('store:profile')

@login_required
def add_to_cart(request):
    user = request.user
    product_id = request.GET.get('prod_id')
    product = get_object_or_404(Product, id=product_id)
    selected_size = request.GET.get('size')

    # Basic validation: if product has sizes, a size must be selected
    if product.available_sizes and not selected_size:
        messages.error(request, "Please select a size for this product.")
        # Re-render detail page with error
        related_products = Product.objects.exclude(id=product.id).filter(is_active=True, category=product.category)[:4]
        p_image = product.p_images.all()
        available_sizes_list = [s.strip() for s in product.available_sizes.split(',') if s.strip()] if product.available_sizes else []
        context_for_render = {
            'product': product,
            'related_products': related_products,
            'p_image': p_image,
            'available_sizes': available_sizes_list,
        }
        return render(request, 'store/detail.html', context_for_render)

    cart_item, created = Cart.objects.get_or_create(
        user=user,
        product=product,
        size=selected_size if selected_size else None, # Store None if no size applicable/selected
        defaults={'quantity': 1}
    )

    if not created:
        cart_item.quantity += 1
        cart_item.save()
        messages.success(request, f"Quantity of {product.title} (Size: {selected_size or 'N/A'}) updated in cart.")
    else:
        messages.success(request, f"Added {product.title} (Size: {selected_size or 'N/A'}) to cart.")

    # Re-render detail page (original behavior) or redirect
    # For re-rendering, ensure full context is available:
    related_products = Product.objects.exclude(id=product.id).filter(is_active=True, category=product.category)[:4]
    p_image = product.p_images.all()
    available_sizes_list = [s.strip() for s in product.available_sizes.split(',') if s.strip()] if product.available_sizes else []
    context_for_render = {
        'product': product,
        'related_products': related_products,
        'p_image': p_image,
        'available_sizes': available_sizes_list,
    }
    return render(request, 'store/detail.html', context_for_render)


@login_required
def cart(request):
    user = request.user
    cart_products = Cart.objects.filter(user=user)
    
    amount = decimal.Decimal(0)
    for item in cart_products:
        amount += item.total_price # Relies on the corrected Cart.total_price property

    shipping_amount = decimal.Decimal(0)
    
    # For displaying applied coupon information (assumes AddCoupon applies one coupon to all items)
    coupon_for_display = None
    first_item_with_coupon = cart_products.filter(coupon__isnull=False, coupon__active=True).first()
    if first_item_with_coupon:
        coupon_for_display = first_item_with_coupon.coupon

    context = {
        'cart_products': cart_products,
        'amount': amount,
        'shipping_amount': shipping_amount,
        'total_amount': amount + shipping_amount,
        'coupon': coupon_for_display,
    }
    return render(request, 'store/cart.html', context)

class AddCoupon(View):
    def post(self, request, *args, **kwargs):
        code = request.POST.get('coupon', '')
        coupon = Coupon.objects.filter(code__iexact=code)

        if coupon.exists():
            # Apply the coupon to the user's cart
            cart_products = Cart.objects.filter(user=request.user)
            active_coupon = coupon.first()
            if not active_coupon.active:
                messages.warning(request, "This coupon is not active.")
                return redirect('store:cart')
            cart_products.update(coupon=active_coupon)  # Assign the coupon to all cart products
            
            messages.success(request, "Coupon applied successfully")
        else:
            messages.warning(request, "Invalid coupon code")

        return redirect('store:cart')

@login_required
def remove_cart(request, cart_id):
    if request.method == 'GET':
        c = get_object_or_404(Cart, id=cart_id)
        c.delete()
        messages.success(request, "Product removed from Cart.")
    return redirect('store:cart')


@login_required
def plus_cart(request, cart_id):
    if request.method == 'GET':
        cp = get_object_or_404(Cart, id=cart_id)
        cp.quantity += 1
        cp.save()
    return redirect('store:cart')


@login_required
def minus_cart(request, cart_id):
    if request.method == 'GET':
        cp = get_object_or_404(Cart, id=cart_id)
        # Remove the Product if the quantity is already 1
        if cp.quantity == 1:
            cp.delete()
        else:
            cp.quantity -= 1
            cp.save()
    return redirect('store:cart')


@login_required
def checkout(request):
    user = request.user
    cart_items = Cart.objects.filter(user=user)
    addresses = Address.objects.filter(user=user) # Assuming you want to show addresses

    if not cart_items.exists():
        messages.warning(request, "Your cart is empty. Please add items to your cart before proceeding to checkout.")
        return redirect('store:cart')

    amount = decimal.Decimal(0)
    for item in cart_items:
        amount += item.total_price

    shipping_amount = decimal.Decimal(0) # Or your actual shipping calculation
    total_amount = amount + shipping_amount

    context = {
        'cart_items': cart_items,
        'addresses': addresses,
        'amount': amount,
        'shipping_amount': shipping_amount,
        'total_amount': total_amount,
    }
    # The actual order creation should happen after this page,
    # e.g., when a "Place Order" button is clicked and payment is processed.
    return render(request, 'store/checkout.html', context)


@login_required
def orders(request):
    all_orders = Order.objects.filter(user=request.user).order_by('-ordered_date')
    return render(request, 'store/orders.html', {'orders': all_orders})





def shop(request):
    return render(request, 'store/shop.html')

def about(request):
    return render(request, 'store/about-us.html')

def contact(request):
    return render(request, 'store/contact.html')



def test(request):
    return render(request, 'store/test.html')
