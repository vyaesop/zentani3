"""Crawler detection, used to keep bot traffic from writing to the database.

Every storefront write wakes the Neon compute for its full 5-minute autosuspend
window, so a crawler walking sitemap.xml can hold the database awake around the
clock and burn the monthly CU allowance without a single real visitor. Bots
still get the page and the markup; they just don't get a session row, an
analytics event or an affiliate click.

Detection is user-agent only, which is trivially spoofable — that is fine.
Misjudging a visitor costs nothing but an unrecorded analytics row, and a bot
that disguises itself as a browser is no worse off than before this existed.
"""
import re

# "bot" is matched only as a trailing token so device names like CUBOT_X30
# (a budget Android handset) are not mistaken for crawlers. Bare product
# families that do not end in "bot" are listed explicitly below.
_CRAWLER_RE = re.compile(
    r"bot[/ ;)\],]|bot$|crawler|spider|slurp|scrapy"
    r"|curl/|wget/|libwww-perl|python-requests|python-urllib|httpx/|aiohttp/"
    r"|okhttp/|go-http-client|java/|axios/|node-fetch|guzzle|postmanruntime"
    r"|facebookexternalhit|embedly|skypeuripreview|whatsapp/|vkshare|outbrain"
    r"|headlesschrome|phantomjs|puppeteer|playwright|lighthouse|w3c_validator"
    r"|uptimerobot|pingdom|statuscake|site24x7|betteruptime|newrelicpinger"
    r"|ahrefs|semrush|mj12|dataforseo|bytespider|chatgpt-user|oai-searchbot"
)

_CACHE_ATTR = "_zent_is_crawler"


def is_crawler(request):
    """True when this request should not produce database writes.

    A missing User-Agent counts as a crawler: every real browser sends one,
    and scripted clients frequently do not.
    """
    if request is None:
        return False
    cached = getattr(request, _CACHE_ATTR, None)
    if cached is not None:
        return cached

    user_agent = (request.META.get("HTTP_USER_AGENT") or "").strip().lower()
    verdict = not user_agent or bool(_CRAWLER_RE.search(user_agent))
    setattr(request, _CACHE_ATTR, verdict)
    return verdict
