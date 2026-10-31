"""Gemini reading of a supplier post: what is for sale, in which colours, at
what price, plus original shopper copy for each item.

The caption is the only source of facts (price, sizes, material); the photos
only decide garment, colour and style. No Google Search grounding: there is
nothing to look up for a local supplier, and the call stays fast and cheap.
"""
import base64
from decimal import Decimal, InvalidOperation

from store.ai_enrichment import (
    ProductAIError,
    _extract_json_text,
    _format_taxonomy_options,
    _safe_json_loads,
    gemini_generate_content,
)

LAYOUTS = ("single", "colours", "separate")


def _prompt(channel_title, caption, photo_count, collection_options):
    return f"""
You are cataloguing one post from a clothing supplier's Telegram channel for Zentanee, an online clothing store in Addis Ababa, Ethiopia.
Supplier: {channel_title}

The caption below is the supplier's own text. It is often English mixed with Amharic and emoji, and it is the ONLY source of facts: price, sizes, material. Never invent a fact the caption does not state.
The {photo_count} attached photos are numbered 0 to {photo_count - 1} in the order attached. Use them for garment type, colour and style details.

Caption:
\"\"\"
{caption or "(no caption)"}
\"\"\"

Existing store collections (slug and title):
{_format_taxonomy_options(collection_options)}

Work through these steps:
1. Decide whether the post sells a specific clothing item or accessory. Announcements, hiring posts, giveaways and general promos are not product posts.
2. Split the post into items: one item per distinct garment AND colour combination. Give each item the photo numbers that show it. A collage photo showing several items belongs to each of them. Give items of the same garment the same "garment" key (g1, g2, ...).
3. layout_guess: "single" when every photo shows one garment in one colour, "colours" when one garment appears in several colours, "separate" when the post shows different garments.
4. supplier_price: the price for ONE piece in birr, as a number. When the caption lists wholesale tiers (for example "1 Pc 1600, 10+ Pcs 1500"), use the single-piece price. When one price covers every item, repeat it on each. Null when the caption has no price.
5. sizes: only the sizes the caption lists, normalised like "S", "M", "L", "XL", "2XL", "Free size". Include plus sizes when listed. Empty list when the caption lists none.
6. supplier_code: a product code the caption states (for example "Product ID: XCL-WJ-P"), else an empty string.
7. For each item write original shopper-facing copy in English:
   - title: a short product name WITHOUT the colour (the colour is stored separately), e.g. "Square-Neck Long Sleeve Tee".
   - short_description: one or two sentences. detail_description: a short paragraph.
   - material, fit_notes, care_notes: only what the caption or a clearly visible detail supports; otherwise an empty string.
   - Never mention prices, sizes, the supplier, phone numbers, Telegram handles, locations, delivery or returns.
   - Never use em dashes or en dashes; use commas, colons or full stops.
8. collection: choose an existing collection slug whenever one reasonably fits. Only when none fits, set matched_slug to null and propose a short, broad name (like "Tops" or "Jeans") with confidence "high" only if the store clearly needs it.

Return strict JSON only, with this shape:
{{
  "is_product_post": true,
  "skip_reason": "string, empty for product posts",
  "layout_guess": "single|colours|separate",
  "supplier_code": "string",
  "items": [
    {{
      "garment": "g1",
      "colour": "string",
      "photos": [0],
      "supplier_price": 0,
      "sizes": ["string"],
      "title": "string",
      "product_type": "string",
      "short_description": "string",
      "detail_description": "string",
      "material": "string",
      "fit_notes": "string",
      "care_notes": "string",
      "seo_title": "string",
      "seo_description": "string",
      "image_alt_text": "string",
      "collection": {{
        "matched_slug": "existing-slug or null",
        "proposed_new_title": "string or null",
        "confidence": "high|medium|low"
      }}
    }}
  ]
}}
""".strip()


def _clean_text(value, limit, *, multiline=False):
    text = str(value or "").strip() if multiline else " ".join(str(value or "").split())
    # Belt and braces for the store-wide "no em dashes" rule.
    text = text.replace(" — ", ", ").replace("—", ", ").replace("–", "-")
    return text[:limit]


def _price(value):
    if value in (None, "", 0, "0"):
        return None
    try:
        amount = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    return amount if amount > 0 else None


def normalize_analysis(raw, photo_count):
    """Validate Gemini's answer into the shape the intake flow relies on.

    Always returns at least one item for a product post, every item has at
    least one in-range photo, and prices are Decimal-compatible strings.
    """
    raw = raw if isinstance(raw, dict) else {}
    all_photos = list(range(photo_count))
    items = []
    for index, entry in enumerate(raw.get("items") or []):
        if not isinstance(entry, dict):
            continue
        photos = []
        for value in entry.get("photos") or []:
            try:
                position = int(value)
            except (TypeError, ValueError):
                continue
            if 0 <= position < photo_count and position not in photos:
                photos.append(position)
        price = _price(entry.get("supplier_price"))
        collection = entry.get("collection") if isinstance(entry.get("collection"), dict) else {}
        items.append(
            {
                "garment": _clean_text(entry.get("garment") or f"g{index + 1}", 20),
                "colour": _clean_text(entry.get("colour"), 80),
                "photos": photos or all_photos,
                "supplier_price": str(price) if price is not None else None,
                "sizes": [_clean_text(size, 20) for size in (entry.get("sizes") or []) if _clean_text(size, 20)],
                "title": _clean_text(entry.get("title"), 150),
                "product_type": _clean_text(entry.get("product_type"), 80),
                "short_description": _clean_text(entry.get("short_description"), 1000, multiline=True),
                "detail_description": _clean_text(entry.get("detail_description"), 3000, multiline=True),
                "material": _clean_text(entry.get("material"), 120),
                "fit_notes": _clean_text(entry.get("fit_notes"), 1000, multiline=True),
                "care_notes": _clean_text(entry.get("care_notes"), 1000, multiline=True),
                "seo_title": _clean_text(entry.get("seo_title"), 180),
                "seo_description": _clean_text(entry.get("seo_description"), 320),
                "image_alt_text": _clean_text(entry.get("image_alt_text"), 180),
                "collection": {
                    "matched_slug": collection.get("matched_slug") or None,
                    "proposed_new_title": collection.get("proposed_new_title") or None,
                    "confidence": collection.get("confidence") or "low",
                },
            }
        )

    is_product_post = bool(raw.get("is_product_post", True))
    if is_product_post and not items:
        is_product_post = False
    layout = raw.get("layout_guess") if raw.get("layout_guess") in LAYOUTS else "single"
    if len(items) <= 1:
        layout = "single"
    return {
        "is_product_post": is_product_post,
        "skip_reason": _clean_text(raw.get("skip_reason"), 200) or ("" if is_product_post else "Not a product post."),
        "layout_guess": layout,
        "supplier_code": _clean_text(raw.get("supplier_code"), 60),
        "items": items,
    }


def analyze_post(*, channel_title, caption, photos, collection_options=()):
    """Ask Gemini to read a supplier post. `photos` is a list of (bytes, mime).

    Raises ProductAIError / ProductAITransientError like the rest of the AI
    layer; the daily job retries failed posts on its next run.
    """
    if not photos:
        raise ProductAIError("A supplier post needs at least one photo.")
    parts = [{"text": _prompt(channel_title, caption, len(photos), collection_options)}]
    for content, mime_type in photos:
        parts.append(
            {
                "inlineData": {
                    "mimeType": mime_type or "image/jpeg",
                    "data": base64.b64encode(content).decode("ascii"),
                }
            }
        )
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
    }
    api_response = gemini_generate_content(payload)
    parsed = _safe_json_loads(_extract_json_text(api_response))
    return normalize_analysis(parsed, len(photos))


def taxonomy_payload(item):
    """Shape an analysed item like an enrichment payload for resolve_taxonomy."""
    return {
        "catalog_fields": {"product_type": item.get("product_type", "")},
        "classification": {"collection": dict(item.get("collection") or {})},
    }
