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
from django.utils.decorators import method_decorator # for Class Based Views
from django.template.loader import render_to_string
from decimal import Decimal
from django.db.models import Sum, F, ExpressionWrapper, DecimalField




# Create your views here.

def home(request):
    categories = Category.objects.filter(is_active=True, is_featured=True).order_by("created_at")[:8]
    brands = Brand.objects.filter(is_active=True, is_featured=True)[:12]

    products = Product.objects.filter(is_active=True, is_featured=True)[:10]
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
    context = {
        'product': product,
        'related_products': related_products,
        'p_image': p_image

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
            form.save()
            return redirect('store:login')  # Redirect to account/login.html
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

    # Check whether the Product is alread in Cart or Not
    item_already_in_cart = Cart.objects.filter(product=product_id, user=user)
    if item_already_in_cart:
        cp = get_object_or_404(Cart, product=product_id, user=user)
        cp.quantity += 1
        cp.save()
    else:
        Cart(user=user, product=product).save()
    
    return render(request, 'store/detail.html', {'product': product})


@login_required

def cart(request):
    user = request.user
    cart_products = Cart.objects.filter(user=user)
    amount = 0
    # Calculate total amount using aggregation and ExpressionWrapper
    if cart_products.exists():
        # Calculate total amount using aggregation and ExpressionWrapper
        expression = ExpressionWrapper(F('quantity') * F('product__price'), output_field=DecimalField())
        amount = cart_products.aggregate(total_amount=Sum(expression)).get('total_amount', 0)
    shipping_amount = decimal.Decimal(40)
    # Check if a coupon is applied
    coupon = None
    if cart_products.filter(coupon__isnull=False).exists():
        coupon = cart_products.first().coupon
        discount = coupon.discount if coupon.discount else 0
        amount = amount - discount

    if request.method == 'POST':
        coupon_code = request.POST.get('coupon')

        try:
            coupon = Coupon.objects.get(code=coupon_code)
        except Coupon.DoesNotExist:
            messages.error(request, 'Invalid coupon code. Please try again.')
        else:
            cart_products.update(coupon=coupon)
            messages.success(request, 'Coupon applied successfully.')

    addresses = Address.objects.filter(user=user)

    context = {
        'cart_products': cart_products,
        'amount': amount,
        'shipping_amount': shipping_amount,
        'total_amount': amount + shipping_amount,
        'addresses': addresses,
        'coupon': coupon,
    }

    return render(request, 'store/cart.html', context)

class AddCoupon(View):
    def __init__(self):
        pass
    def post(self, request, *args, **kwargs):
        code = request.POST.get('coupon', '')
        coupon = Coupon.objects.filter(code__iexact=code)

        if coupon.exists():
            # Apply the coupon to the user's cart
            cart_products = Cart.objects.filter(user=request.user)
            cart_products.update(coupon=coupon.first())  # Assign the coupon to all cart products
            
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
    address_id = request.GET.get('address')
    
    address = get_object_or_404(Address, id=address_id)
    # Get all the products of User in Cart
    cart = Cart.objects.filter(user=user)
    for c in cart:
        # Saving all the products from Cart to Order
        Order(user=user, address=address, product=c.product, quantity=c.quantity).save()
        # And Deleting from Cart
        c.delete()
    return redirect('store:orders')


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
