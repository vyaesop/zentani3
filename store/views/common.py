"""Cross-cutting request helpers shared by the view modules."""
import decimal
from decimal import Decimal

from django.conf import settings
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme


def _safe_redirect_url(request, fallback_url):
    candidate = (
        request.POST.get("next")
        or request.GET.get("next")
        or request.META.get("HTTP_REFERER")
    )
    if candidate and url_has_allowed_host_and_scheme(
        url=candidate,
        allowed_hosts={request.get_host(), *getattr(settings, "ALLOWED_HOSTS", [])},
        require_https=request.is_secure(),
    ):
        return candidate
    return fallback_url


def _safe_redirect_url_with_query(request, fallback_url):
    resolved = _safe_redirect_url(request, fallback_url)
    if resolved.startswith("/"):
        return resolved
    try:
        return reverse(resolved)
    except Exception:
        return reverse(fallback_url)


def _normalized_multi_param(values):
    seen = []
    for value in values:
        normalized = (value or "").strip()
        if normalized and normalized not in seen:
            seen.append(normalized)
    return seen


def _parse_decimal_param(value):
    normalized = (value or "").strip()
    if not normalized:
        return None

    try:
        return Decimal(normalized)
    except decimal.InvalidOperation:
        return None


def _querydict_pairs(querydict):
    pairs = []
    for key, values in querydict.lists():
        for value in values:
            pairs.append((key, value))
    return pairs


def _querystring_without(request, *keys_to_remove):
    params = request.GET.copy()
    for key in keys_to_remove:
        params.pop(key, None)
    encoded = params.urlencode()
    return f"{encoded}&" if encoded else ""


def _url_with_query(path, params):
    encoded = params.urlencode()
    if not encoded:
        return path
    return f"{path}?{encoded}"


def _ensure_session_key(request):
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def _is_htmx(request):
    return request.headers.get("HX-Request") == "true"
