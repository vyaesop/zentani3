"""Registration, profile, and address management."""
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View

from store.forms import AddressForm, RegistrationForm
from store.models import Address, AffiliateProfile, BackgroundTask, Order, Wishlist
from store.tasks import enqueue

from .catalog import _saved_product_ids_for_user
from .common import _safe_redirect_url_with_query


def _build_profile_flow_status(addresses, orders):
    if not addresses.exists():
        return {
            "tone": "warning",
            "eyebrow": "Account setup",
            "title": "Add your delivery address",
            "message": "A saved address makes checkout faster and prevents order delays.",
            "primary_label": "Add address",
            "primary_url": reverse("store:add-address"),
        }

    if not orders.exists():
        return {
            "tone": "info",
            "eyebrow": "Next step",
            "title": "Your account is ready for checkout",
            "message": "Start shopping, add items to your cart, and place your first order when ready.",
            "primary_label": "Browse products",
            "primary_url": reverse("store:all-products"),
            "secondary_label": "Open cart",
            "secondary_url": reverse("store:cart"),
        }

    return {
        "tone": "success",
        "eyebrow": "Account status",
        "title": "Your account is active and ready",
        "message": "Manage addresses here and track your order progress from the orders section.",
        "primary_label": "View orders",
        "primary_url": reverse("store:orders"),
        "secondary_label": "Manage addresses",
        "secondary_url": reverse("store:profile"),
    }


class RegistrationView(View):
    def get(self, request):
        form = RegistrationForm()
        return render(request, "account/register.html", {"form": form, "next_url": request.GET.get("next", "")})

    def post(self, request):
        form = RegistrationForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                user = form.save()
                signup_address = Address.objects.create(
                    user=user,
                    address=form.cleaned_data.get("address"),
                    city=form.cleaned_data.get("city"),
                    phone=form.cleaned_data.get("username"),
                )

            # Re-authenticate so Django can attach the correct backend when multiple backends are configured.
            authenticated_user = authenticate(
                request,
                username=form.cleaned_data.get("username"),
                password=form.cleaned_data.get("password1"),
            )
            if authenticated_user is not None:
                login(request, authenticated_user)

            enqueue(
                BackgroundTask.TYPE_TELEGRAM_SIGNUP_NOTIFY,
                {"user_id": user.id, "address_id": signup_address.id},
            )
            messages.success(request, "Account created successfully. You can continue with your order now.")
            return redirect(_safe_redirect_url_with_query(request, "store:profile"))
        return render(request, "account/register.html", {"form": form, "next_url": request.POST.get("next", "")})


@login_required
def profile(request):
    addresses = Address.objects.filter(user=request.user).order_by("-id")
    orders = Order.objects.filter(user=request.user).select_related("product").only(
        "id",
        "quantity",
        "size",
        "status",
        "ordered_date",
        "line_total",
        "price_at_purchase",
        "product__id",
        "product__title",
        "product__slug",
    )
    saved_items = (
        Wishlist.objects.filter(user=request.user)
        .select_related("product", "product__category", "product__brand")
        .only(
            "id",
            "created_at",
            "product__id",
            "product__slug",
            "product__title",
            "product__price",
            "product__product_image",
            "product__available_sizes",
            "product__is_sold_out",
            "product__category__title",
            "product__category__slug",
            "product__brand__title",
            "product__brand__slug",
        )[:6]
    )
    has_affiliate_profile = AffiliateProfile.objects.filter(user=request.user).exists()
    profile_flow_status = _build_profile_flow_status(addresses, orders)
    return render(
        request,
        "account/profile.html",
        {
            "addresses": addresses,
            "orders": orders,
            "saved_items": saved_items,
            "saved_product_ids": _saved_product_ids_for_user(request.user),
            "has_affiliate_profile": has_affiliate_profile,
            "profile_flow_status": profile_flow_status,
        },
    )


@method_decorator(login_required, name="dispatch")
class AddressView(View):
    def get(self, request):
        form = AddressForm()
        return render(request, "account/add_address.html", {"form": form, "next_url": request.GET.get("next", "")})

    def post(self, request):
        form = AddressForm(request.POST)
        if form.is_valid():
            user = request.user
            address = form.cleaned_data["address"]
            city = form.cleaned_data["city"]
            phone = form.cleaned_data["phone"]
            reg = Address(user=user, address=address, city=city, phone=phone)
            reg.save()
            redirect_target = _safe_redirect_url_with_query(request, "store:profile")
            if redirect_target == reverse("store:cart"):
                messages.success(request, "Address saved. You can now return to your cart and place the order.")
            else:
                messages.success(request, "New address added successfully.")
            return redirect(redirect_target)
        return render(request, "account/add_address.html", {"form": form, "next_url": request.POST.get("next", "")})


@login_required
def remove_address(request, id):
    if request.method != "POST":
        messages.warning(request, "Invalid request method.")
        return redirect("store:profile")

    a = get_object_or_404(Address, user=request.user, id=id)
    a.delete()
    messages.success(request, "Address removed.")
    return redirect("store:profile")
