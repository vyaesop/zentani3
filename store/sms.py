"""Pluggable SMS delivery.

Backends (settings.SMS_BACKEND):
    disabled     never sends; returns False so callers can fall back.
    console      prints the message (local development / tests).
    afromessage  AfroMessage (Ethiopian gateway) JSON API.
    http         Generic JSON POST described by SMS_HTTP_URL / SMS_HTTP_BODY.

All backends return True on success and False on failure and never raise:
notification code decides whether a failure should be retried by the queue.
"""
import json
import logging
from urllib import error, request

from django.conf import settings

from store.phone import to_e164

logger = logging.getLogger(__name__)

SMS_TIMEOUT_SECONDS = 8


def sms_enabled():
    return (getattr(settings, "SMS_BACKEND", "disabled") or "disabled").lower() not in {"", "disabled"}


def _post_json(url, payload, headers=None):
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with request.urlopen(req, timeout=SMS_TIMEOUT_SECONDS) as response:
            status = getattr(response, "status", 200)
            return 200 <= status < 300
    except (error.URLError, error.HTTPError, TimeoutError, OSError) as exc:
        logger.warning("SMS gateway request failed: %s", exc)
        return False


def _send_afromessage(to_number, message):
    token = getattr(settings, "AFROMESSAGE_TOKEN", "")
    if not token:
        logger.warning("SMS_BACKEND=afromessage but AFROMESSAGE_TOKEN is empty.")
        return False
    payload = {
        "to": to_number,
        "message": message,
        "sender": getattr(settings, "SMS_SENDER_ID", "") or "",
    }
    identifier = getattr(settings, "AFROMESSAGE_IDENTIFIER_ID", "")
    if identifier:
        payload["from"] = identifier
    return _post_json(
        getattr(settings, "AFROMESSAGE_API_URL", "https://api.afromessage.com/api/send"),
        payload,
        headers={"Authorization": f"Bearer {token}"},
    )


def _render_template(template, **values):
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", json.dumps(str(value))[1:-1])
    return rendered


def _send_http(to_number, message):
    url = getattr(settings, "SMS_HTTP_URL", "")
    if not url:
        logger.warning("SMS_BACKEND=http but SMS_HTTP_URL is empty.")
        return False
    sender = getattr(settings, "SMS_SENDER_ID", "") or ""
    try:
        headers = json.loads(_render_template(getattr(settings, "SMS_HTTP_HEADERS", "{}") or "{}", to=to_number, message=message, sender=sender))
        body = json.loads(_render_template(getattr(settings, "SMS_HTTP_BODY", "{}") or "{}", to=to_number, message=message, sender=sender))
    except ValueError as exc:
        logger.warning("SMS_HTTP_HEADERS/SMS_HTTP_BODY is not valid JSON: %s", exc)
        return False
    return _post_json(url, body, headers=headers)


def send_sms(phone, message):
    """Send one SMS. Returns True when delivered to the gateway."""
    backend = (getattr(settings, "SMS_BACKEND", "disabled") or "disabled").lower()
    if backend in {"", "disabled"}:
        return False
    to_number = to_e164(phone)
    if not to_number:
        logger.info("SMS skipped: %r is not a valid Ethiopian mobile number.", phone)
        return False
    text = (message or "").strip()
    if not text:
        return False

    if backend == "console":
        print(f"[sms -> {to_number}] {text}")  # noqa: T201 - intentional console backend
        return True
    if backend == "afromessage":
        return _send_afromessage(to_number, text)
    if backend == "http":
        return _send_http(to_number, text)
    logger.warning("Unknown SMS_BACKEND %r; SMS not sent.", backend)
    return False
