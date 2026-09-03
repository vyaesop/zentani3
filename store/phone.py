"""Ethiopian phone-number normalisation.

Accepted inputs (spaces, dashes and dots are ignored):
    0911234567   911234567   +251911234567   251911234567   00251911234567
    0711234567 (Safaricom Ethiopia) in the same shapes.

Canonical local form is ``09XXXXXXXX`` / ``07XXXXXXXX`` — the format existing
customers already log in with — and ``+2519XXXXXXXX`` for E.164 (SMS gateways).
"""
import re

_SEPARATORS_RE = re.compile(r"[\s\-\.\(\)]")
_MOBILE_PREFIXES = ("9", "7")


def _digits(value):
    text = _SEPARATORS_RE.sub("", str(value or "").strip())
    if text.startswith("+"):
        text = text[1:]
    if not text.isdigit():
        return None
    return text


def normalize_et_phone(value):
    """Return the canonical local form (``09XXXXXXXX``) or None when invalid."""
    digits = _digits(value)
    if not digits:
        return None
    if digits.startswith("00251"):
        digits = digits[5:]
    elif digits.startswith("251"):
        digits = digits[3:]
    elif digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 9 or digits[0] not in _MOBILE_PREFIXES:
        return None
    return f"0{digits}"


def to_e164(value):
    """``+2519XXXXXXXX`` for gateways, or None when the number is invalid."""
    local = normalize_et_phone(value)
    if not local:
        return None
    return f"+251{local[1:]}"


def looks_like_phone(value):
    return normalize_et_phone(value) is not None
