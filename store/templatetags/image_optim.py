from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

_UPLOAD_MARKER = "/upload/"


def _is_cloudinary_url(url):
    return bool(url) and "res.cloudinary.com" in url and _UPLOAD_MARKER in url


def _transformed_url(url, width):
    """Insert Cloudinary delivery transforms (auto format/quality, capped width)."""
    if not _is_cloudinary_url(url):
        return url
    transform = f"f_auto,q_auto,c_limit,w_{int(width)}"
    return url.replace(_UPLOAD_MARKER, f"{_UPLOAD_MARKER}{transform}/", 1)


def _image_url(image):
    """Accept a FieldFile or a plain URL string; empty string when absent."""
    if not image:
        return ""
    url = getattr(image, "url", None)
    if url:
        return url
    return image if isinstance(image, str) else ""


@register.simple_tag(name="cld_url")
def cld_url(image, width=600):
    """Cloudinary delivery URL at the given CSS-pixel width (raw URL fallback)."""
    return _transformed_url(_image_url(image), width)


@register.simple_tag(name="cld_img")
def cld_img(image, width=600, alt="", css_class="", loading="lazy", fetchpriority="", html_width=None, html_height=None, img_id=""):
    """Render an <img> served through Cloudinary with a 1x/2x srcset.

    Falls back to the raw file URL when Cloudinary is not configured so local
    development keeps working. Pass loading="eager" plus
    fetchpriority="high" for the LCP image; everything else stays lazy.
    """
    url = _image_url(image)
    if not url:
        return ""

    attributes = []
    if img_id:
        attributes.append(format_html('id="{}"', img_id))
    if css_class:
        attributes.append(format_html('class="{}"', css_class))
    if _is_cloudinary_url(url):
        attributes.append(format_html('src="{}"', _transformed_url(url, width)))
        attributes.append(
            format_html(
                'srcset="{} 1x, {} 2x"',
                _transformed_url(url, width),
                _transformed_url(url, int(width) * 2),
            )
        )
    else:
        attributes.append(format_html('src="{}"', url))
    attributes.append(format_html('alt="{}"', alt or ""))
    if html_width and html_height:
        attributes.append(format_html('width="{}" height="{}"', html_width, html_height))
    if loading == "eager":
        attributes.append(format_html('loading="eager"'))
    else:
        attributes.append(format_html('loading="lazy"'))
    if fetchpriority:
        attributes.append(format_html('fetchpriority="{}"', fetchpriority))
    attributes.append(format_html('decoding="async"'))
    return mark_safe("<img " + " ".join(attributes) + ">")


@register.filter(name="cdn_optimize")
def cdn_optimize(url):
    """Legacy filter: apply Cloudinary auto format/quality to a URL."""
    if not url:
        return url
    if _is_cloudinary_url(url) and "f_auto,q_auto" not in url and "f_webp,q_auto" not in url:
        return url.replace(_UPLOAD_MARKER, f"{_UPLOAD_MARKER}f_auto,q_auto/", 1)
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
