from store.forms import LoginForm, PasswordChangeForm, PasswordResetForm, SetPasswordForm
from django.urls import path
from . import views
from django.contrib.auth import views as auth_views


app_name = 'store'


urlpatterns = [
    path('', views.home, name="home"),
    # URL for Cart and Checkout
    path('add-to-cart/', views.add_to_cart, name="add-to-cart"),
    path('add-coupon/', views.AddCoupon.as_view(), name="add-coupon"),
    path('remove-cart/<int:cart_id>/', views.remove_cart, name="remove-cart"),
    path('plus-cart/<int:cart_id>/', views.plus_cart, name="plus-cart"),
    path('minus-cart/<int:cart_id>/', views.minus_cart, name="minus-cart"),
    path('cart/', views.cart, name="cart"),
    path('checkout/', views.checkout, name="checkout"),
    path('orders/', views.orders, name="orders"),
    path("search/", views.search_view, name="search"),
    path("filter-products/", views.filter_product, name="filter-product"),
    path('products/', views.products, name="all-products"),
    path('brands/', views.all_brands, name="all-brands"),
    path('brand/<slug:slug>/', views.brand_products, name="brand-products"),
    path('product/test/', views.test, name="test"),
    path('about/', views.about, name="about"),
    path('contact/', views.contact, name="contact"),

    #URL for Products
    path('product/<slug:slug>/', views.detail, name="product-detail"),
    path('categories/', views.all_categories, name="all-categories"),
    path('<slug:slug>/', views.category_products, name="category-products"),


    path('shop/', views.shop, name="shop"),

    # URL for Authentication
    path('accounts/register/', views.RegistrationView.as_view(), name="register"),
    path('accounts/login/', auth_views.LoginView.as_view(template_name='account/login.html', authentication_form=LoginForm), name="login"),
    path('accounts/profile/', views.profile, name="profile"),
    path('accounts/add-address/', views.AddressView.as_view(), name="add-address"),
    path('accounts/remove-address/<int:id>/', views.remove_address, name="remove-address"),
    path('accounts/logout/', auth_views.LogoutView.as_view(next_page='store:login'), name="logout"),

    path('accounts/password-change/', auth_views.PasswordChangeView.as_view(template_name='account/password_change.html', form_class=PasswordChangeForm, success_url='/accounts/password-change-done/'), name="password-change"),
    path('accounts/password-change-done/', auth_views.PasswordChangeDoneView.as_view(template_name='account/password_change_done.html'), name="password-change-done"),

    path('accounts/password-reset/', auth_views.PasswordResetView.as_view(template_name='account/password_reset.html', form_class=PasswordResetForm, success_url='/accounts/password-reset/done/'), name="password-reset"), # Passing Success URL to Override default URL, also created password_reset_email.html due to error from our app_name in URL
    path('accounts/password-reset/done/', auth_views.PasswordResetDoneView.as_view(template_name='account/password_reset_done.html'), name="password_reset_done"),
    path('accounts/password-reset-confirm/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(template_name='account/password_reset_confirm.html', form_class=SetPasswordForm, success_url='/accounts/password-reset-complete/'), name="password_reset_confirm"), # Passing Success URL to Override default URL
    path('accounts/password-reset-complete/', auth_views.PasswordResetCompleteView.as_view(template_name='account/password_reset_complete.html'), name="password_reset_complete"),


    
]
# def cart(request):
#     user = request.user
#     cart_products = Cart.objects.filter(user=user)

#     # Display Total on Cart Page
#     amount = decimal.Decimal(0)
#     shipping_amount = decimal.Decimal(40)
#     # using list comprehension to calculate total amount based on quantity and shipping
#     cp = [p for p in Cart.objects.all() if p.user==user]
#     if cp:
#         for p in cp:
#             temp_amount = (p.quantity * p.product.price)
#             amount += temp_amount

#     # Customer Addresses
#     addresses = Address.objects.filter(user=user)

#     context = {
#         'cart_products': cart_products,
#         'amount': amount,
#         'shipping_amount': shipping_amount,
#         'total_amount': amount + shipping_amount,
#         'addresses': addresses,
#     }
#     return render(request, 'store/cart.html', context)
