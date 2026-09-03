"""Scrape the gojoshop.et storefront into this store's catalog.

This crawls the public, server-rendered GOJO Shop storefront (a 6valley /
Laravel marketplace) and imports products into the local Product / Category /
Brand / ProductImages models.

WHY A LOCAL SCRIPT: gojoshop.et blocks datacenter/proxy egress, so the scrape
must run from a machine with normal internet access (e.g. your laptop or the
production box). Run it there.

Dependencies (not in requirements.txt yet):
    pip install requests beautifulsoup4

Typical use:
    # 1. See what it would do, no DB writes, dump parsed data to JSON:
    python manage.py scrape_gojoshop --limit 20 --output-json gojo_sample.json --skip-images

    # 2. Full run, writing to the DB and downloading images:
    python manage.py scrape_gojoshop

    # 3. Just one product, printing the parsed dict (for debugging selectors):
    python manage.py scrape_gojoshop --url https://gojoshop.et/product/beanie-cap-QS64nR --debug --dry-run

Flags:
    --limit N          Stop after N products (0 = no limit).
    --dry-run          Parse only; never touch the database.
    --output-json PATH Write every parsed product to a JSON array at PATH.
    --skip-images      Do not download images (faster; leaves product_image unset on new rows).
    --refresh-images   Re-download images even if the product already has one.
    --url URL          Scrape specific product URL(s) instead of the whole sitemap; repeatable.
    --debug            Print the parsed dict for each product.
    --sleep SECONDS    Delay between page fetches (default 0.5) to be polite.
    --max-price N      Skip DB import of products priced above N (model cap is 999999.99).
    --to-ai-queue      Create ProductAIDraft rows (image + sku + price + sizes) and enqueue
                       them for Gemini enrichment instead of creating Products directly.
                       Drain the queue with `python manage.py run_tasks`.

NOTE ON CONTENT: this copies GOJO Shop's product names, descriptions and images
verbatim, which are the vendors' copyrighted content. That is what was requested;
make sure you have the right to republish it before going live.
"""

from __future__ import annotations

import json
import re
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlparse

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from store.models import Brand, Category, Product, ProductImages

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError as exc:  # pragma: no cover
    raise CommandError(
        "This command needs `requests` and `beautifulsoup4`.\n"
        "Install them with:  pip install requests beautifulsoup4"
    ) from exc

BASE = "https://gojoshop.et"
SITEMAP = f"{BASE}/sitemap.xml"
PRICE_MODEL_CAP = Decimal("999999.99")  # Product.price is DecimalField(max_digits=8, decimal_places=2)

HEADERS = {
    # Present as a normal browser; the site 403s obvious bots.
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept-Language": "en",
}

PRICE_RE = re.compile(r"([\d][\d,]*\.\d{2})\s*ETB", re.IGNORECASE)


class Command(BaseCommand):
    help = "Scrape gojoshop.et products into the local catalog."

    # ---- CLI ---------------------------------------------------------------
    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--output-json", type=str, default="")
        parser.add_argument("--skip-images", action="store_true")
        parser.add_argument("--refresh-images", action="store_true")
        parser.add_argument("--url", action="append", default=[], help="Scrape specific product URL(s); repeatable.")
        parser.add_argument("--debug", action="store_true")
        parser.add_argument("--sleep", type=float, default=0.5)
        parser.add_argument("--max-price", type=float, default=float(PRICE_MODEL_CAP))
        parser.add_argument(
            "--to-ai-queue",
            action="store_true",
            help=(
                "Instead of creating Products directly, create ProductAIDraft rows "
                "(scraped image + sku + price + sizes) and enqueue them for the Gemini "
                "enrichment pipeline, which writes the copy/taxonomy and creates the product."
            ),
        )

    # ---- entrypoint --------------------------------------------------------
    def handle(self, *args, **opts):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.opts = opts

        if opts["to_ai_queue"] and not opts["dry_run"]:
            from store.ai_enrichment import gemini_is_configured

            if not gemini_is_configured():
                self.stderr.write(
                    self.style.WARNING(
                        "GEMINI_API_KEY is not configured — drafts will queue but enrichment will fail."
                    )
                )

        if opts["url"]:
            urls = list(opts["url"])
        else:
            urls = self.collect_product_urls()
            self.stdout.write(f"Found {len(urls)} product URLs.")
            if opts["limit"]:
                urls = urls[: opts["limit"]]

        parsed_all = []
        imported = skipped = failed = 0

        for i, url in enumerate(urls, 1):
            try:
                data = self.parse_product(url)
            except Exception as exc:  # keep going on individual failures
                failed += 1
                self.stderr.write(self.style.WARNING(f"[{i}/{len(urls)}] FAIL {url}: {exc}"))
                continue

            parsed_all.append(data)
            if opts["debug"]:
                self.stdout.write(json.dumps(data, ensure_ascii=False, indent=2))

            if opts["dry_run"]:
                self.stdout.write(f"[{i}/{len(urls)}] parsed (dry-run): {data['title'][:60]}")
            else:
                if opts["to_ai_queue"]:
                    result = self.queue_ai_draft(data)
                else:
                    result = self.import_product(data)
                if result in ("imported", "queued"):
                    imported += 1
                else:
                    skipped += 1
                self.stdout.write(f"[{i}/{len(urls)}] {result}: {data['title'][:60]}")

            time.sleep(opts["sleep"])

        if opts["output_json"]:
            with open(opts["output_json"], "w", encoding="utf-8") as fh:
                json.dump(parsed_all, fh, ensure_ascii=False, indent=2)
            self.stdout.write(self.style.SUCCESS(f"Wrote {len(parsed_all)} records to {opts['output_json']}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. parsed={len(parsed_all)} imported={imported} skipped={skipped} failed={failed}"
            )
        )

    # ---- URL discovery -----------------------------------------------------
    def collect_product_urls(self) -> list[str]:
        """All product URLs from sitemap.xml, plus a pass over category listings
        to catch products the sitemap may omit."""
        urls: set[str] = set()

        # 1. sitemap.xml
        try:
            xml = self.session.get(SITEMAP, timeout=30).text
            urls.update(re.findall(r"<loc>\s*(https://gojoshop\.et/product/[^<\s]+)\s*</loc>", xml))
        except Exception as exc:
            self.stderr.write(self.style.WARNING(f"sitemap fetch failed: {exc}"))

        # 2. Paginated "latest" feed — walks the whole catalog even if the
        #    sitemap is capped. Stops when a page yields no new product links.
        page = 1
        empty_streak = 0
        while empty_streak < 2 and page <= 500:
            try:
                html = self.session.get(
                    f"{BASE}/products?data_from=latest&page={page}", timeout=30
                ).text
            except Exception:
                break
            found = set(re.findall(r"https://gojoshop\.et/product/[^\"'<>\s]+", html))
            new = found - urls
            urls.update(found)
            empty_streak = empty_streak + 1 if not new else 0
            page += 1
            time.sleep(self.opts["sleep"])

        # Clean HTML-entity artifacts and dedupe.
        return sorted({u.replace("&amp;", "&").split("?")[0] for u in urls})

    # ---- parsing -----------------------------------------------------------
    def parse_product(self, url: str) -> dict:
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")

        ld = self._json_ld_product(soup)

        def meta(prop, attr="property"):
            tag = soup.find("meta", {attr: prop})
            return tag["content"].strip() if tag and tag.get("content") else ""

        # Title: visible product heading first, then JSON-LD, then og:title.
        title = self._visible_title(soup) or (ld.get("name") if ld else "") or meta("og:title")
        title = (title or "").strip()

        # Description
        detail_html = self._overview_html(soup)
        short = meta("og:description") or meta("description", "name") or ""
        if ld and not short:
            short = (ld.get("description") or "").strip()

        # Price + compare-at
        price, compare_at = self._prices(soup, ld, html)

        # Images (full-size, ordered, deduped)
        images = self._images(soup, ld, meta("og:image"))

        # Category from breadcrumb / JSON-LD
        category = self._category(soup, ld)

        brand = self._brand(ld)
        sold_out = self._sold_out(ld)
        sizes = self._sizes(soup)

        return {
            "url": url,
            "sku": self._sku(url),
            "title": title,
            "short_description": short,
            "detail_description": detail_html,
            "price": str(price) if price is not None else None,
            "compare_at_price": str(compare_at) if compare_at is not None else None,
            "category": category,
            "brand": brand,
            "images": images,
            "sizes": sizes,
            "is_sold_out": sold_out,
            "keywords": meta("keywords", "name"),
        }

    def _json_ld_product(self, soup):
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(tag.string or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            candidates = data if isinstance(data, list) else [data]
            for c in candidates:
                if isinstance(c, dict) and "Product" in str(c.get("@type", "")):
                    return c
        return {}

    def _visible_title(self, soup):
        # 6valley product page renders the name in an <h1>/<h2> near the price.
        for sel in ["h1", "h2.title", "h2.mb-2", ".product-details-info h2", ".product-title"]:
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                return el.get_text(strip=True)
        return ""

    def _overview_html(self, soup):
        # Overview tab content.
        for sel in ["#overview", ".product-description", "#description", ".long-description"]:
            el = soup.select_one(sel)
            if el:
                inner = el.decode_contents().strip()
                if inner:
                    return inner
        return ""

    def _prices(self, soup, ld, html):
        price = compare_at = None
        # Prefer JSON-LD offer price.
        if ld:
            offers = ld.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price = self._to_decimal(offers.get("price"))
        # Struck-through / compare price from markup.
        struck = soup.select_one("del, .old-price, .strikethrough, s")
        if struck:
            compare_at = self._to_decimal_from_text(struck.get_text())
        # Fallback: first ETB price on the page.
        if price is None:
            m = PRICE_RE.search(html)
            if m:
                price = self._to_decimal_from_text(m.group(1))
        # If we found a compare price but it's not higher, drop it.
        if price is not None and compare_at is not None and compare_at <= price:
            compare_at = None
        return price, compare_at

    def _images(self, soup, ld, og_image):
        seen, out = set(), []

        def add(u):
            if not u:
                return
            u = urljoin(BASE, u.strip())
            # Full-size product images live under /storage/product/ (skip thumbs/meta).
            if "/storage/product/" not in u:
                return
            if "/thumbnail/" in u or "/meta/" in u:
                return
            if u not in seen:
                seen.add(u)
                out.append(u)

        add(og_image)
        if ld:
            img = ld.get("image")
            for u in (img if isinstance(img, list) else [img]):
                add(u if isinstance(u, str) else "")
        for tag in soup.find_all("img"):
            add(tag.get("data-src") or tag.get("src"))
        return out

    def _category(self, soup, ld):
        if ld and ld.get("category"):
            return str(ld["category"]).strip()
        crumbs = soup.select(".breadcrumb a, nav[aria-label='breadcrumb'] a")
        names = [a.get_text(strip=True) for a in crumbs if a.get_text(strip=True)]
        names = [n for n in names if n.lower() not in ("home", "")]
        if names:
            return names[-1]
        return "Uncategorized"

    @staticmethod
    def _brand(ld):
        # Only trust JSON-LD; scanning the page for a "Brand" label matches the
        # site-wide brands nav dropdown and returns an unrelated brand.
        raw = (ld or {}).get("brand")
        name = raw.get("name", "") if isinstance(raw, dict) else (raw or "")
        name = str(name).strip()
        return "" if name.lower() in ("", "no brand") else name

    @staticmethod
    def _sold_out(ld):
        # Every page contains hidden "Out of stock" template markup (modal,
        # similar-product cards), so grepping the HTML always matches. JSON-LD
        # offers.availability is the reliable signal.
        offers = (ld or {}).get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        availability = str(offers.get("availability", ""))
        return "outofstock" in availability.replace(" ", "").lower()

    def _sizes(self, soup):
        sizes = []
        for el in soup.select("[name='choice_0'] option, .variant-size, label.size, .choice_attributes label"):
            txt = el.get_text(strip=True)
            if txt and txt.lower() not in ("choose", "select"):
                sizes.append(txt)
        return sizes

    # ---- helpers -----------------------------------------------------------
    @staticmethod
    def _sku(url):
        slug = urlparse(url).path.rstrip("/").split("/")[-1]
        token = slug.rsplit("-", 1)[-1]  # trailing id, e.g. QS64nR
        return token or slug

    @staticmethod
    def _to_decimal(value):
        if value is None:
            return None
        try:
            return Decimal(str(value).replace(",", "")).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            return None

    def _to_decimal_from_text(self, text):
        m = re.search(r"[\d][\d,]*(?:\.\d{1,2})?", text or "")
        return self._to_decimal(m.group(0)) if m else None

    # ---- import ------------------------------------------------------------
    @transaction.atomic
    def import_product(self, data) -> str:
        if not data["title"] or data["price"] is None:
            return "skipped(no title/price)"

        price = Decimal(data["price"])
        if price > Decimal(str(self.opts["max_price"])):
            return f"skipped(price {price} over cap)"

        category = self._get_category(data["category"])
        brand = self._get_brand(data["brand"]) if data["brand"] else None

        defaults = {
            "title": data["title"][:150],
            "slug": slugify(data["title"])[:160] or slugify(data["sku"]),
            "short_description": data["short_description"] or data["title"],
            "detail_description": data["detail_description"],
            "price": price,
            "compare_at_price": Decimal(data["compare_at_price"]) if data["compare_at_price"] else None,
            "category": category,
            "brand": brand,
            "is_active": True,
            "is_featured": False,
            "is_sold_out": data["is_sold_out"],
            "stock_quantity": 0 if data["is_sold_out"] else Product.DEFAULT_STOCK_PER_SIZE,
            "seo_title": data["title"][:180],
            "seo_description": (data["short_description"] or data["title"])[:320],
        }

        product, created = Product.objects.get_or_create(
            sku=data["sku"], defaults={**defaults, "product_image": ""}
        )
        if not created:
            for k, v in defaults.items():
                setattr(product, k, v)

        # Images
        if not self.opts["skip_images"] and data["images"]:
            need_main = self.opts["refresh_images"] or not getattr(product.product_image, "name", "")
            if need_main:
                main = self._download(data["images"][0])
                if main:
                    product.product_image.save(self._img_name(data["sku"], data["images"][0]), main, save=False)
            product.save()
            # Gallery (skip the first / main image). Stored names carry the
            # upload_to prefix (product-images/...), so compare basenames.
            existing = {
                pi.image.name.rsplit("/", 1)[-1]
                for pi in product.p_images.all()
                if getattr(pi.image, "name", "")
            }
            for idx, img_url in enumerate(data["images"][1:], 1):
                name = self._img_name(f"{data['sku']}-{idx}", img_url)
                if name in existing:
                    continue
                content = self._download(img_url)
                if not content:
                    continue
                pi = ProductImages(product=product)
                pi.image.save(name, content, save=True)
        else:
            # No image downloaded; product_image is required, so only save if it
            # already has one (updates) — new rows without an image are skipped.
            if not getattr(product.product_image, "name", ""):
                if created:
                    product.delete()
                    return "skipped(no image; use without --skip-images)"
            product.save()

        # Sizes / inventory
        if data["sizes"] and not data["is_sold_out"]:
            try:
                from store.services.inventory import set_product_sizes

                set_product_sizes(product, data["sizes"])
            except Exception as exc:
                self.stderr.write(self.style.WARNING(f"size set failed for {data['sku']}: {exc}"))

        return "imported"

    def queue_ai_draft(self, data) -> str:
        """Create a ProductAIDraft from the scraped image/sku/price/sizes and
        enqueue it for Gemini enrichment, which writes the copy and taxonomy
        and creates the (unpublished) product itself.

        Not atomic on purpose: with TASKS_EAGER (DEBUG default) enqueue()
        runs the Gemini call inline, which must not happen inside a
        transaction. A draft left queued without a task is re-enqueued by
        the orphan sweeper."""
        from django.contrib.auth import get_user_model

        from store.models import BackgroundTask, ProductAIDraft
        from store.tasks import enqueue

        if not data["images"]:
            return "skipped(no image; AI draft needs a reference image)"
        if data["price"] is None:
            return "skipped(no price)"
        if data["is_sold_out"]:
            return "skipped(sold out at source)"

        price = Decimal(data["price"])
        if price > Decimal(str(self.opts["max_price"])):
            return f"skipped(price {price} over cap)"

        if Product.objects.filter(sku=data["sku"]).exists():
            return "skipped(product with this sku exists)"
        if ProductAIDraft.objects.filter(sku=data["sku"]).exists():
            return "skipped(draft with this sku exists)"

        owner = getattr(self, "_draft_owner", None)
        if owner is None:
            User = get_user_model()
            owner = (
                User.objects.filter(is_superuser=True).order_by("id").first()
                or User.objects.filter(is_staff=True).order_by("id").first()
            )
            if owner is None:
                raise CommandError("--to-ai-queue needs a superuser or staff user to own the drafts.")
            self._draft_owner = owner

        content = self._download(data["images"][0])
        if not content:
            return "skipped(reference image download failed)"

        draft = ProductAIDraft(
            created_by=owner,
            sku=data["sku"],
            price=price,
            sizes=", ".join(data["sizes"])[:100],
            pipeline_state=ProductAIDraft.PIPELINE_QUEUED,
            queued_at=timezone.now(),
        )
        draft.reference_image.save(self._img_name(data["sku"], data["images"][0]), content, save=True)
        enqueue(BackgroundTask.TYPE_AI_ENRICH_DRAFT, {"draft_id": draft.id})
        return "queued"

    def _get_category(self, title):
        title = (title or "Uncategorized").strip()[:50]
        obj, _ = Category.objects.get_or_create(
            title=title,
            defaults={"slug": slugify(title)[:55] or "uncat", "is_active": True, "is_featured": False},
        )
        return obj

    def _get_brand(self, title):
        title = title.strip()[:50]
        obj, _ = Brand.objects.get_or_create(
            title=title,
            defaults={"slug": slugify(title)[:55] or "brand", "is_active": True, "is_featured": False},
        )
        return obj

    def _download(self, url):
        try:
            r = self.session.get(url, timeout=30)
            r.raise_for_status()
            return ContentFile(r.content)
        except Exception as exc:
            self.stderr.write(self.style.WARNING(f"image download failed {url}: {exc}"))
            return None

    @staticmethod
    def _img_name(stem, url):
        ext = urlparse(url).path.split(".")[-1].lower()
        if ext not in ("jpg", "jpeg", "png", "webp", "gif"):
            ext = "jpg"
        return f"{slugify(stem)}.{ext}"
