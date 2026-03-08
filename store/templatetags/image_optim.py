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
