"""Views package (split from the former store/views.py monolith).

`store/urls.py` imports view callables from here; each submodule owns one
domain: catalog browsing, cart, checkout, account, affiliate, telegram,
payments, feeds, and static pages.
"""
from .account import AddressView, RateLimitedLoginView, RegistrationView, profile, remove_address
from .affiliate import affiliate_dashboard, track_affiliate_link
from .cart import AddCoupon, add_to_cart, cart, minus_cart, plus_cart, remove_cart
from .catalog import (
    about,
    contact,
    delivery_returns,
    detail,
    home,
    request_restock,
    review_invite,
    service_worker,
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
    sale_products,
    search_suggestions,
    search_view,
)
from .checkout import cancel_order, checkout, order_confirmation, orders
from .feeds import google_merchant_feed
from .pages import faq, privacy, robots_txt, terms
from .payments import chapa_return, chapa_webhook
from .telegram import admin_telegram_webhook, customer_telegram_webhook, telegram_webhook

__all__ = [
    "AddCoupon", "AddressView", "RateLimitedLoginView", "RegistrationView",
    "about", "add_to_cart", "admin_telegram_webhook", "affiliate_dashboard",
    "all_brands", "all_categories", "brand_products", "cancel_order", "cart",
    "category_products", "chapa_return", "chapa_webhook", "checkout", "contact",
    "customer_telegram_webhook", "delivery_returns", "detail", "faq",
    "google_merchant_feed", "home", "minus_cart", "order_confirmation", "orders",
    "plus_cart", "privacy", "products", "profile", "remove_address", "remove_cart",
    "request_restock", "review_invite", "robots_txt", "sale_products",
    "search_suggestions", "search_view", "service_worker", "shop", "submit_review",
    "telegram_webhook", "terms", "test", "toggle_wishlist", "track_affiliate_link",
]
