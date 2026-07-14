"""Views package (split from the former store/views.py monolith).

`store/urls.py` imports view callables from here; each submodule owns one
domain: catalog browsing, cart, checkout, account, affiliate, telegram.
"""
from .account import AddressView, RegistrationView, profile, remove_address
from .affiliate import affiliate_dashboard, track_affiliate_link
from .cart import AddCoupon, add_to_cart, cart, minus_cart, plus_cart, remove_cart
from .catalog import (
    about,
    contact,
    detail,
    home,
    request_restock,
    shop,
    submit_review,
    test,
    toggle_wishlist,
)
from .collections import (
    all_brands,
    all_categories,
    brand_products,
    category_products,
    products,
    search_suggestions,
    search_view,
)
from .checkout import cancel_order, checkout, orders
from .telegram import admin_telegram_webhook, customer_telegram_webhook, telegram_webhook

__all__ = [
    "AddCoupon", "AddressView", "RegistrationView",
    "about", "add_to_cart", "admin_telegram_webhook", "affiliate_dashboard",
    "all_brands", "all_categories", "brand_products", "cancel_order", "cart",
    "category_products", "checkout", "contact", "customer_telegram_webhook",
    "detail", "home", "minus_cart", "orders", "plus_cart", "products",
    "profile", "remove_address", "remove_cart", "request_restock",
    "search_suggestions", "search_view", "shop", "submit_review",
    "telegram_webhook", "test", "toggle_wishlist", "track_affiliate_link",
]
