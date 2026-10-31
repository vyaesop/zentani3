"""Read supplier listings from a public Telegram channel's web preview.

t.me/s/<channel> serves the newest ~20 posts as HTML with no account or API
key, and `?before=<id>` pages further back. Captions come back as text and
photos as Telegram CDN URLs (capped around 800px tall). That is enough for
the review flow: the pictures shoppers see are made by an admin, the
supplier's photos are only the reference.

The owner of a channel can turn the preview off at any time; the page then
returns no posts and the channel simply yields nothing until it is back.
"""
import hashlib
import html
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.request import Request, urlopen

PREVIEW_URL = "https://t.me/s/{username}"
EMBED_URL = "https://t.me/{username}/{message_id}?embed=1&mode=tme"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
# A daily run normally needs one page per channel; the cap only bounds the
# first backfill (about 20 posts per page).
MAX_PAGES = 30
PAGE_DELAY_SECONDS = 1.5
# Telegram albums hold at most 10 photos, and so does the review album.
MAX_PHOTOS_PER_LISTING = 10
# Suppliers often post each colour as its own photo with one shared caption,
# seconds or minutes apart. Same caption within this window = one listing.
SPLIT_LISTING_WINDOW = timedelta(minutes=30)

_MESSAGE_SPLIT = re.compile(r'<div class="tgme_widget_message_wrap')
_POST_ID = re.compile(r'data-post="[^"/]+/(\d+)"')
_PHOTO = re.compile(
    r"tgme_widget_message_photo_wrap[^\"]*\"[^>]*style=\"[^\"]*background-image:url\('([^']+)'\)"
)
_TEXT = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)
_TIME = re.compile(r'<time datetime="([^"]+)"')
_BR = re.compile(r"<br\s*/?>", re.I)
_TAG = re.compile(r"<[^>]+>")


@dataclass
class ChannelMessage:
    message_id: int
    posted_at: datetime
    caption: str
    photo_urls: list = field(default_factory=list)


@dataclass
class Listing:
    message_id: int
    posted_at: datetime
    caption: str
    message_ids: list = field(default_factory=list)
    photo_urls: list = field(default_factory=list)
    last_posted_at: datetime = None


def _html_to_text(fragment):
    text = _TAG.sub("", _BR.sub("\n", fragment))
    return html.unescape(text).strip()


def parse_preview_page(page_html):
    """All messages on a preview page (photo or not), oldest first."""
    messages = []
    for chunk in _MESSAGE_SPLIT.split(page_html or "")[1:]:
        post_id = _POST_ID.search(chunk)
        posted = _TIME.search(chunk)
        if not post_id or not posted:
            continue
        try:
            posted_at = datetime.fromisoformat(posted.group(1))
        except ValueError:
            continue
        text = _TEXT.search(chunk)
        messages.append(
            ChannelMessage(
                message_id=int(post_id.group(1)),
                posted_at=posted_at,
                caption=_html_to_text(text.group(1)) if text else "",
                photo_urls=[html.unescape(url) for url in _PHOTO.findall(chunk)],
            )
        )
    messages.sort(key=lambda message: message.message_id)
    return messages


def _fetch_text(url, timeout=20):
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_preview_page(username, before=None):
    url = PREVIEW_URL.format(username=username)
    if before:
        url = f"{url}?before={before}"
    return _fetch_text(url)


def fetch_new_messages(username, *, after_id, since, fetch=fetch_preview_page, sleep=time.sleep):
    """Messages newer than `after_id` and posted at or after `since`, oldest first.

    Walks back page by page and stops as soon as a page reaches either
    boundary, so a daily run costs one request per quiet channel.
    """
    collected = {}
    before = None
    for _ in range(MAX_PAGES):
        page = parse_preview_page(fetch(username, before))
        if not page:
            break
        for message in page:
            if message.message_id > after_id and message.posted_at >= since:
                collected[message.message_id] = message
        oldest = page[0]
        if oldest.message_id <= after_id or oldest.posted_at < since:
            break
        if before is not None and oldest.message_id >= before:
            break  # The page did not move back; never loop forever.
        before = oldest.message_id
        sleep(PAGE_DELAY_SECONDS)
    return sorted(collected.values(), key=lambda message: message.message_id)


def caption_hash(caption):
    normalized = " ".join((caption or "").split()).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def group_listings(messages):
    """Turn photo messages into listings, merging split colour posts.

    Text-only messages (announcements, hiring posts, links) never become
    listings. Albums already arrive as one message from the preview.
    """
    listings = []
    for message in messages:
        if not message.photo_urls:
            continue
        previous = listings[-1] if listings else None
        if (
            previous is not None
            and caption_hash(message.caption)
            and caption_hash(message.caption) == caption_hash(previous.caption)
            and message.posted_at - previous.last_posted_at <= SPLIT_LISTING_WINDOW
            and len(previous.photo_urls) < MAX_PHOTOS_PER_LISTING
        ):
            previous.message_ids.append(message.message_id)
            room = MAX_PHOTOS_PER_LISTING - len(previous.photo_urls)
            previous.photo_urls.extend(message.photo_urls[:room])
            previous.last_posted_at = message.posted_at
            continue
        listings.append(
            Listing(
                message_id=message.message_id,
                posted_at=message.posted_at,
                caption=message.caption,
                message_ids=[message.message_id],
                photo_urls=list(message.photo_urls[:MAX_PHOTOS_PER_LISTING]),
                last_posted_at=message.posted_at,
            )
        )
    return listings


def photo_fingerprint(content):
    """Shape hash plus centre colour of a photo, as 22 hex chars ("" if unreadable).

    Suppliers repost the very same photo when they restock, so a matching
    fingerprint spots a repost even when the caption changed, while two
    garments sharing a generic caption ("New Design Top") stay apart. The
    colour part matters: suppliers shoot every colour with the same model in
    the same pose, which the grayscale shape hash alone cannot tell apart.
    """
    from io import BytesIO

    from PIL import Image, ImageStat

    try:
        with Image.open(BytesIO(content)) as image:
            rgb = image.convert("RGB")
            pixels = list(rgb.convert("L").resize((9, 8)).getdata())
            width, height = rgb.size
            centre = rgb.crop((width // 4, height // 4, 3 * width // 4, 3 * height // 4)).resize((32, 32))
            red, green, blue = (round(value) for value in ImageStat.Stat(centre).mean)
    except Exception:  # noqa: BLE001
        return ""
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (pixels[row * 9 + col] > pixels[row * 9 + col + 1])
    return f"{bits:016x}{red:02x}{green:02x}{blue:02x}"


# Measured on the real channels: reposts differ by 0 bits and 0 colour
# levels; different colours shot in the same pose differ by 10+ levels.
MAX_SHAPE_DISTANCE = 2
MAX_COLOUR_DIFFERENCE = 6


def fingerprints_match(first, second):
    if len(first or "") != 22 or len(second or "") != 22:
        return False
    shape_distance = bin(int(first[:16], 16) ^ int(second[:16], 16)).count("1")
    colour_difference = max(
        abs(int(first[16 + i:18 + i], 16) - int(second[16 + i:18 + i], 16)) for i in (0, 2, 4)
    )
    return shape_distance <= MAX_SHAPE_DISTANCE and colour_difference <= MAX_COLOUR_DIFFERENCE


def refresh_photo_urls(username, message_id):
    """Fresh CDN URLs for one post, for when stored ones have gone stale."""
    page = _fetch_text(EMBED_URL.format(username=username, message_id=message_id))
    return [html.unescape(url) for url in _PHOTO.findall(page)]


def download(url, timeout=20, max_bytes=10 * 1024 * 1024):
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        content = resp.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise ValueError(f"{url} is larger than {max_bytes} bytes.")
    return content
