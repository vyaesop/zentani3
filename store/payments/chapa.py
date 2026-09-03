"""Chapa hosted checkout (Telebirr, CBE Birr, M-Pesa, cards) for optional prepay.

Flow: `initialize_payment` creates a transaction and returns the hosted
checkout URL; the shopper pays there and is sent to our return URL, and Chapa
also POSTs a webhook. Both paths call `verify_payment` against the Chapa API
before anything is marked paid — the redirect and the webhook body are hints,
never proof.

Everything here uses urllib so no new dependency is needed; failures raise
ChapaError with a message safe to show staff.
"""
import hashlib
import hmac
import json
import logging
from decimal import Decimal
from urllib import error, request

from django.conf import settings

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 15


class ChapaError(Exception):
    """Chapa returned an error or could not be reached."""


def is_enabled():
    return bool(getattr(settings, "CHAPA_SECRET_KEY", "")) and getattr(settings, "ONLINE_PAYMENTS_ENABLED", False)


def _api(path, payload=None, method=None):
    secret = getattr(settings, "CHAPA_SECRET_KEY", "")
    if not secret:
        raise ChapaError("Chapa is not configured (CHAPA_SECRET_KEY is empty).")
    url = f"{getattr(settings, 'CHAPA_API_BASE_URL', 'https://api.chapa.co/v1')}{path}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = request.Request(url, data=body, method=method or ("POST" if body else "GET"))
    req.add_header("Authorization", f"Bearer {secret}")
    req.add_header("Content-Type", "application/json")
    try:
        with request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")[:300]
        except Exception:  # noqa: BLE001
            pass
        logger.warning("Chapa %s failed: HTTP %s %s", path, exc.code, detail)
        raise ChapaError(f"Chapa rejected the request (HTTP {exc.code}).") from exc
    except (error.URLError, TimeoutError, OSError) as exc:
        logger.warning("Chapa %s unreachable: %s", path, exc)
        raise ChapaError("Chapa could not be reached. Please try again or choose cash on delivery.") from exc
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ChapaError("Chapa returned an unreadable response.") from exc
    if str(data.get("status", "")).lower() != "success":
        raise ChapaError(data.get("message") or "Chapa reported a failure.")
    return data.get("data") or {}


def tx_ref_for(group):
    return f"{group.number}-{group.id}"


def initialize_payment(group, *, return_url, callback_url):
    """Create the hosted checkout; returns the URL to redirect the shopper to."""
    contact = group.contact or {}
    first_name, _, last_name = (contact.get("full_name") or "Customer").partition(" ")
    payload = {
        "amount": f"{Decimal(group.total):.2f}",
        "currency": "ETB",
        "tx_ref": tx_ref_for(group),
        "phone_number": (contact.get("phone") or "").replace("+", ""),
        "first_name": first_name[:50],
        "last_name": (last_name or "-")[:50],
        "return_url": return_url,
        "callback_url": callback_url,
        "customization": {
            "title": getattr(settings, "STORE_NAME", "Zentanee")[:16],
            "description": f"Order {group.number}"[:50],
        },
    }
    email = contact.get("email") or ""
    if email:
        payload["email"] = email
    data = _api("/transaction/initialize", payload)
    checkout_url = data.get("checkout_url")
    if not checkout_url:
        raise ChapaError("Chapa did not return a checkout URL.")
    return checkout_url


def verify_payment(tx_ref):
    """Return the verified transaction dict; raises ChapaError when unpaid."""
    data = _api(f"/transaction/verify/{tx_ref}")
    status = str(data.get("status", "")).lower()
    if status != "success":
        raise ChapaError(f"Payment {tx_ref} is not complete (status: {status or 'unknown'}).")
    return data


def payment_matches(group, verified):
    """The verified amount and currency must match what we expect."""
    try:
        amount = Decimal(str(verified.get("amount")))
    except Exception:  # noqa: BLE001
        return False
    currency = str(verified.get("currency", "")).upper()
    return currency == "ETB" and amount >= Decimal(group.total)


def webhook_signature_valid(raw_body, headers):
    """Chapa signs webhooks with the webhook secret two ways; accept either.

    `Chapa-Signature` is HMAC-SHA256(secret, body) and `x-chapa-signature` is
    HMAC-SHA256(secret, secret). Without a configured secret every webhook is
    rejected — the return-URL path still verifies payments in that case.
    """
    secret = getattr(settings, "CHAPA_WEBHOOK_SECRET", "")
    if not secret:
        return False
    provided = (headers.get("Chapa-Signature") or headers.get("x-chapa-signature") or "").strip()
    if not provided:
        return False
    key = secret.encode("utf-8")
    body_sig = hmac.new(key, raw_body or b"", hashlib.sha256).hexdigest()
    secret_sig = hmac.new(key, key, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided, body_sig) or hmac.compare_digest(provided, secret_sig)
