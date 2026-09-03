"""SEO helpers shared by views, forms and the AI enrichment pipeline."""
import re

# Gemini occasionally returns its template literally ("| [Store Name]",
# "[Your Store Name]", "{brand}"). Anything bracketed is treated as unfilled.
_PLACEHOLDER_RE = re.compile(r"\[[^\]]*\]|\{[^}]*\}|<[^>]*>")
_PLACEHOLDER_WORDS_RE = re.compile(
    r"\b(your store name|store name|brand name|insert|lorem ipsum|tbd|todo|placeholder)\b",
    re.IGNORECASE,
)


def has_placeholder(value):
    """True when a piece of merchandising copy still contains template text."""
    text = (value or "").strip()
    if not text:
        return False
    if _PLACEHOLDER_RE.search(text):
        return True
    return bool(_PLACEHOLDER_WORDS_RE.search(text))


def strip_placeholder(value, fallback=""):
    """Return the copy with bracketed template fragments removed.

    "Nike Air Force 1 | [Store Name]" becomes "Nike Air Force 1". When nothing
    meaningful survives, `fallback` is returned instead.
    """
    text = (value or "").strip()
    if not text:
        return fallback
    cleaned = _PLACEHOLDER_RE.sub("", text)
    cleaned = _PLACEHOLDER_WORDS_RE.sub("", cleaned)
    # Tidy separators left dangling by the removal ("Title | " -> "Title").
    cleaned = re.sub(r"\s*[|\-–—:]\s*$", "", cleaned)
    cleaned = re.sub(r"^\s*[|\-–—:]\s*", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned or fallback


def clean_seo_copy(value, fallback=""):
    """Sanitised copy: placeholders removed, or the fallback when unusable."""
    if not has_placeholder(value):
        return (value or "").strip() or fallback
    return strip_placeholder(value, fallback=fallback)
