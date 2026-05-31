from django import template

register = template.Library()


@register.filter(name="cdn_optimize")
def cdn_optimize(url):
    """Apply Cloudinary optimization params with explicit WebP delivery."""
    if not url:
        return url

    marker = "/upload/"
    if "res.cloudinary.com" in url and marker in url and "f_webp,q_auto" not in url:
        return url.replace(marker, "/upload/f_webp,q_auto/", 1)
    return url


@register.filter(name="etb")
def format_etb(value):
    """Format a number as Ethiopian Birr with thousands separator."""
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "—"
    if amount == int(amount):
        return f"{int(amount):,} ETB"
    return f"{amount:,.2f} ETB"


@register.filter(name="split")
def split_string(value, separator=","):
    """Split a string by separator and return a list."""
    if not value:
        return []
    return [part for part in str(value).split(separator) if part.strip()]


@register.filter(name="strip")
def strip_string(value):
    """Strip whitespace from a string."""
    return str(value).strip()


@register.simple_tag
def star_icons(rating, max_rating=5):
    """Return safe HTML star spans for a numeric rating."""
    from django.utils.html import format_html_join
    from django.utils.safestring import mark_safe
    try:
        filled_count = int(round(float(rating)))
    except (TypeError, ValueError):
        filled_count = 0
    filled_count = max(0, min(filled_count, max_rating))
    parts = []
    for i in range(1, max_rating + 1):
        css = "spring-star is-filled" if i <= filled_count else "spring-star"
        parts.append(f'<span class="{css}" aria-hidden="true">★</span>')
    return mark_safe("".join(parts))
