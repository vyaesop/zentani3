from django import template

register = template.Library()


@register.filter(name="cdn_optimize")
def cdn_optimize(url):
    """Apply lightweight Cloudinary optimization params when possible."""
    if not url:
        return url

    marker = "/upload/"
    if "res.cloudinary.com" in url and marker in url and "f_auto,q_auto" not in url:
        return url.replace(marker, "/upload/f_auto,q_auto/", 1)
    return url
