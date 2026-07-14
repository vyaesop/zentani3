"""Affiliate dashboard and referral link tracking."""
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from store.constants import (
    AFFILIATE_CLICK_SESSION_KEY,
    AFFILIATE_SESSION_KEY,
    AFFILIATE_SESSION_MAX_AGE_SECONDS,
)
from store.models import AffiliateClick, AffiliateCommission, AffiliateProfile, Product

from .common import _ensure_session_key


def _affiliate_profile_from_session(request):
    affiliate_profile_id = request.session.get(AFFILIATE_SESSION_KEY)
    if not affiliate_profile_id:
        return None
    return AffiliateProfile.objects.filter(id=affiliate_profile_id, is_active=True).select_related("user").first()


@login_required
def affiliate_dashboard(request):
    affiliate_profile, _ = AffiliateProfile.objects.get_or_create(
        user=request.user,
        defaults={"code": AffiliateProfile.generate_unique_code()},
    )

    if not affiliate_profile.code:
        affiliate_profile.code = AffiliateProfile.generate_unique_code()
        affiliate_profile.save(update_fields=["code", "updated_at"])

    base_ref_link = request.build_absolute_uri(reverse("store:affiliate-track", args=[affiliate_profile.code]))
    default_share_link = f"{base_ref_link}?next=/"
    total_clicks = AffiliateClick.objects.filter(affiliate=affiliate_profile).count()
    total_converted_clicks = AffiliateClick.objects.filter(affiliate=affiliate_profile, converted=True).count()

    commissions = AffiliateCommission.objects.filter(affiliate=affiliate_profile).select_related("order", "customer").order_by("-created_at")
    products_for_sharing = Product.objects.filter(is_active=True, is_sold_out=False).only("id", "title", "slug").order_by("-created_at")[:24]
    pending_total = commissions.filter(status="Pending").aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    paid_total = commissions.filter(status="Paid").aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    lifetime_total = commissions.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

    context = {
        "affiliate_profile": affiliate_profile,
        "base_ref_link": base_ref_link,
        "default_share_link": default_share_link,
        "total_clicks": total_clicks,
        "total_converted_clicks": total_converted_clicks,
        "pending_total": pending_total,
        "paid_total": paid_total,
        "lifetime_total": lifetime_total,
        "commissions": commissions[:25],
        "products_for_sharing": products_for_sharing,
    }
    return render(request, "account/affiliate_dashboard.html", context)


def track_affiliate_link(request, code):
    affiliate_profile = get_object_or_404(AffiliateProfile.objects.select_related("user"), code=code, is_active=True)

    # Prevent self-referrals.
    if request.user.is_authenticated and request.user.id == affiliate_profile.user_id:
        messages.info(request, "You cannot use your own affiliate link.")
        return redirect("store:home")

    request.session[AFFILIATE_SESSION_KEY] = affiliate_profile.id
    request.session.set_expiry(AFFILIATE_SESSION_MAX_AGE_SECONDS)
    session_key = _ensure_session_key(request)

    click = AffiliateClick.objects.create(
        affiliate=affiliate_profile,
        session_key=session_key,
        ip_address=request.META.get("REMOTE_ADDR"),
        user_agent=(request.META.get("HTTP_USER_AGENT") or "")[:300],
        landing_path=(request.GET.get("next") or "")[:300],
    )
    request.session[AFFILIATE_CLICK_SESSION_KEY] = click.id

    destination = request.GET.get("next") or "/"
    if url_has_allowed_host_and_scheme(
        url=destination,
        allowed_hosts={request.get_host(), *getattr(settings, "ALLOWED_HOSTS", [])},
        require_https=request.is_secure(),
    ):
        return redirect(destination)
    return redirect("store:home")
