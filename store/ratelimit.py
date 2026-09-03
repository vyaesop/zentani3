"""Cache-backed attempt counters for login and registration.

Not a full WAF — the aim is to make credential stuffing against phone-number
usernames expensive. Counters live in the Django cache, so with Redis they
are shared across processes; with LocMem they are per-process (still useful,
just weaker). Keys are scoped by IP and by the submitted identifier.
"""
from django.conf import settings
from django.core.cache import cache


def _limit():
    return int(getattr(settings, "LOGIN_RATE_LIMIT_ATTEMPTS", 10) or 10)


def _window():
    return int(getattr(settings, "LOGIN_RATE_LIMIT_WINDOW_SECONDS", 900) or 900)


def client_ip(request):
    forwarded = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    return forwarded or request.META.get("REMOTE_ADDR") or "unknown"


def _keys(scope, request, identifier=""):
    keys = [f"rl:{scope}:ip:{client_ip(request)}"]
    ident = (identifier or "").strip().casefold()
    if ident:
        keys.append(f"rl:{scope}:id:{ident[:80]}")
    return keys


def is_blocked(scope, request, identifier=""):
    limit = _limit()
    for key in _keys(scope, request, identifier):
        if (cache.get(key) or 0) >= limit:
            return True
    return False


def record_failure(scope, request, identifier=""):
    window = _window()
    for key in _keys(scope, request, identifier):
        if cache.add(key, 1, window):
            continue
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, window)


def clear(scope, request, identifier=""):
    cache.delete_many(_keys(scope, request, identifier))


def retry_after_minutes():
    return max(1, _window() // 60)
