import base64
import json
import re
import time
from io import BytesIO
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils.text import slugify

try:
    from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps
except ImportError:
    Image = None
    ImageChops = None
    ImageEnhance = None
    ImageFilter = None
    ImageOps = None


class ProductAIError(Exception):
    pass


RETRYABLE_HTTP_STATUS_CODES = {429, 500, 503}


def gemini_is_configured():
    return bool(getattr(settings, "GEMINI_API_KEY", "").strip())


def infer_vendor_hint_from_sku(sku):
    tokens = [token for token in re.split(r"[^A-Za-z0-9]+", (sku or "").strip()) if token]
    if not tokens:
        return ""

    for token in tokens[:2]:
        if any(char.isalpha() for char in token) and len(token) >= 2:
            return token.upper()
    return ""


def _prompt_for_product_enrichment(sku, price, vendor_hint):
    vendor_text = vendor_hint or "unknown"
    price_text = str(price) if price not in (None, "") else "unknown"
    return f"""
You are helping a local e-commerce merchandising team create a product draft from a single identifier image.

The uploaded image is a private reference image used only to identify the item and guide future image generation briefs.
Do not assume the image itself will be used as the storefront hero image.
The vendor hint is manually provided by the merchandiser and may refer to a local Ethiopian supplier that is not visible on the public web.
Treat sizes as manual business data owned by the merchandiser. Do not infer or fabricate sizes.
The store may carry jewelry, accessories, gift items, collectibles, and fashion products. Do not assume every product is clothing.

Storefront image style references:
- A dark luxury hero image for a single object on a black background with controlled reflections and dramatic lighting.
- A bright clean macro jewelry image on a white background with subtle reflections and close detail visibility.
- A modest-fashion dress and abaya product page with clear color fidelity, drape visibility, and full-length framing when the source image allows it.
- A secondary gallery image can be used only as visual inspiration for alternative framing or detail emphasis, never as a source of factual copy.
Use those as stylistic directions only when appropriate for the detected product type.

Known inputs:
- SKU: {sku}
- Manual vendor hint: {vendor_text}
- Price: {price_text}

Tasks:
1. Identify the product from the image as accurately as possible.
2. Use Google Search grounding to look for exact SKU matches first, then strong same-vendor or highly similar matches when the vendor hint appears useful. If the vendor hint is a local sourcing label with no public footprint, say that clearly instead of pretending to match it online.
3. Draft original store copy that is inspired by grounded facts but does not copy competitor wording.
4. If a detail is uncertain, say so in the confidence notes instead of inventing facts.
5. Create image-generation briefs for a free reference-guided generator. The briefs must preserve the exact product, while improving only lighting, background, crop, and presentation.
6. Tailor the shot plan to the detected product type:
   - For jewelry and rings, prioritize macro detail, gemstone clarity, metal finish, and balanced reflections.
   - For coins, medallions, and collectible metal items, prioritize edge definition, engraved detail, and premium dark-background hero compositions.
   - For dresses, abayas, and modest fashion products, prioritize silhouette, drape, sleeve detail, and clean luxury framing with true-to-product color.
   - For fashion products more broadly, prioritize silhouette, texture, and clean e-commerce framing.

Return strict JSON only with this shape:
{{
  "catalog_fields": {{
    "title": "string",
    "slug_hint": "string",
    "short_description": "string",
    "detail_description": "string",
    "material": "string",
    "color": "string",
    "fit_notes": "string",
    "care_notes": "string",
    "delivery_note": "string",
    "return_note": "string",
    "suggested_category": "string",
    "suggested_brand": "string",
    "product_type": "string"
  }},
  "search_strategy": {{
    "vendor_hint": "string",
    "exact_queries": ["string"],
    "fallback_queries": ["string"]
  }},
  "confidence": {{
    "overall": "high|medium|low",
    "reasoning_notes": ["string"],
    "needs_manual_review": ["string"]
  }},
  "sources": [
    {{
      "title": "string",
      "url": "https://example.com",
      "match_type": "exact|vendor|similar",
      "notes": "string"
    }}
  ],
  "image_plan": {{
    "reference_preservation_notes": "string",
    "negative_prompt": "string",
    "shots": [
      {{
        "name": "Studio White Hero",
        "prompt": "string",
        "aspect_ratio": "1:1 or 4:5",
        "priority": 1
      }}
    ]
  }}
}}
""".strip()


def _extract_json_text(api_response):
    candidates = api_response.get("candidates") or []
    if not candidates:
        raise ProductAIError("Gemini did not return any candidates.")

    candidate = candidates[0]
    parts = ((candidate.get("content") or {}).get("parts")) or []
    for part in parts:
        text = part.get("text")
        if text:
            return text
    raise ProductAIError("Gemini did not return a JSON response body.")


def _extract_grounded_links(api_response):
    links = []
    candidates = api_response.get("candidates") or []
    for candidate in candidates:
        grounding = candidate.get("groundingMetadata") or {}
        for chunk in grounding.get("groundingChunks") or []:
            web = chunk.get("web") or {}
            uri = web.get("uri")
            title = web.get("title")
            if uri:
                links.append({"title": title or uri, "url": uri})

    deduped = []
    seen = set()
    for link in links:
        key = link["url"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(link)
    return deduped


def _safe_json_loads(text):
    normalized = (text or "").strip()
    if normalized.startswith("```"):
        normalized = re.sub(r"^```(?:json)?\s*", "", normalized)
        normalized = re.sub(r"\s*```$", "", normalized)

    try:
        return json.loads(normalized)
    except json.JSONDecodeError as exc:
        start = normalized.find("{")
        end = normalized.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(normalized[start:end + 1])
            except json.JSONDecodeError:
                pass
        raise ProductAIError("Gemini returned malformed JSON.") from exc


def _normalize_payload(payload):
    normalized = {
        "catalog_fields": payload.get("catalog_fields") or {},
        "search_strategy": payload.get("search_strategy") or {},
        "confidence": payload.get("confidence") or {},
        "sources": payload.get("sources") or [],
        "image_plan": payload.get("image_plan") or {},
    }
    return normalized


def _candidate_models():
    primary = getattr(settings, "GEMINI_PRODUCT_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
    fallback = getattr(settings, "GEMINI_PRODUCT_FALLBACK_MODEL", "gemini-2.5-flash-lite").strip()
    models = [primary]
    if fallback and fallback not in models:
        models.append(fallback)
    return models


def _default_shots_for_payload(payload):
    catalog_fields = payload.get("catalog_fields") or {}
    product_type = (catalog_fields.get("product_type") or "").lower()
    category = (catalog_fields.get("suggested_category") or "").lower()
    combined = f"{product_type} {category}"

    if any(term in combined for term in ["abaya", "dress", "modest", "gown"]):
        return [
            {"name": "Studio White Hero", "aspect_ratio": "4:5", "priority": 1, "prompt": "Full-length catalog hero on a clean white background with true purple color fidelity and soft floor shadow."},
            {"name": "Soft Editorial Portrait", "aspect_ratio": "4:5", "priority": 2, "prompt": "A premium neutral editorial backdrop that preserves the abaya silhouette and fabric drape."},
            {"name": "Fabric Detail Crop", "aspect_ratio": "1:1", "priority": 3, "prompt": "A closer crop emphasizing sleeve, texture, and drape detail without changing the garment."},
        ]
    if any(term in combined for term in ["ring", "jewelry", "gemstone"]):
        return [
            {"name": "Studio White Hero", "aspect_ratio": "1:1", "priority": 1, "prompt": "Bright white hero with balanced reflections and clear gemstone detail."},
            {"name": "Luxury Dark Hero", "aspect_ratio": "1:1", "priority": 2, "prompt": "Dark luxury jewelry composition with controlled reflections."},
            {"name": "Detail Macro", "aspect_ratio": "1:1", "priority": 3, "prompt": "Macro crop centered on the main gemstone and prong details."},
        ]
    if any(term in combined for term in ["coin", "collectible", "medallion"]):
        return [
            {"name": "Dark Luxury Hero", "aspect_ratio": "1:1", "priority": 1, "prompt": "Premium black backdrop highlighting the coin edge and engraved face."},
            {"name": "Macro Detail", "aspect_ratio": "1:1", "priority": 2, "prompt": "Close crop showing engraving detail and metallic texture."},
            {"name": "Angled View", "aspect_ratio": "1:1", "priority": 3, "prompt": "A subtle angled composition for depth without changing the item."},
        ]
    return [
        {"name": "Studio White Hero", "aspect_ratio": "4:5", "priority": 1, "prompt": "Clean catalog hero on a white background."},
        {"name": "Luxury Dark Hero", "aspect_ratio": "4:5", "priority": 2, "prompt": "Premium dark-background hero that preserves the item."},
        {"name": "Detail Crop", "aspect_ratio": "1:1", "priority": 3, "prompt": "Tighter product crop for texture and detail."},
    ]


def _resolve_shots(payload):
    image_plan = payload.get("image_plan") or {}
    shots = image_plan.get("shots") or []
    return shots or _default_shots_for_payload(payload)


def _parse_aspect_ratio(raw_value):
    value = (raw_value or "").strip()
    if value == "4:5":
        return (1200, 1500)
    return (1200, 1200)


def _cover_resize(image, size):
    return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS)


def _contain_resize(image, size):
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    contained = ImageOps.contain(image, (int(size[0] * 0.88), int(size[1] * 0.88)), method=Image.Resampling.LANCZOS)
    left = (size[0] - contained.width) // 2
    top = (size[1] - contained.height) // 2
    canvas.alpha_composite(contained, (left, top))
    return canvas


def _subject_shadow(subject, size, opacity=70, blur_radius=34, y_offset=32):
    alpha = subject.getchannel("A")
    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    shadow_mask = Image.new("RGBA", subject.size, (0, 0, 0, opacity))
    shadow_mask.putalpha(alpha)
    left = (size[0] - subject.width) // 2
    top = (size[1] - subject.height) // 2 + y_offset
    shadow.alpha_composite(shadow_mask, (left, top))
    return shadow.filter(ImageFilter.GaussianBlur(blur_radius))


def _render_white_hero(reference_rgba, size):
    background = Image.new("RGBA", size, "#f8f4ee")
    background = Image.alpha_composite(background, _linear_gradient(size, ("#ffffff", "#efe7db")))
    subject = _contain_resize(reference_rgba, size)
    canvas = Image.alpha_composite(background, _subject_shadow(subject, size, opacity=58, blur_radius=26, y_offset=20))
    return Image.alpha_composite(canvas, subject)


def _render_dark_hero(reference_rgba, size):
    background = Image.new("RGBA", size, "#101010")
    background = Image.alpha_composite(background, _radial_glow(size, "#2b2332", intensity=0.45))
    subject = _contain_resize(reference_rgba, size)
    enhanced = ImageEnhance.Contrast(subject).enhance(1.12)
    enhanced = ImageEnhance.Color(enhanced).enhance(1.04)
    canvas = Image.alpha_composite(background, _subject_shadow(enhanced, size, opacity=94, blur_radius=36, y_offset=26))
    return _add_vignette(Image.alpha_composite(canvas, enhanced), 0.24)


def _render_detail_crop(reference_rgba, size):
    cropped = _detail_focus(reference_rgba, size)
    cropped = ImageEnhance.Sharpness(cropped).enhance(1.35)
    cropped = ImageEnhance.Contrast(cropped).enhance(1.08)
    background = Image.new("RGBA", size, "#ffffff")
    return Image.alpha_composite(background, cropped)


def _render_soft_editorial(reference_rgba, size):
    background = Image.new("RGBA", size, "#ece4df")
    background = Image.alpha_composite(background, _linear_gradient(size, ("#f7f1ec", "#d9cdc7")))
    subject = _contain_resize(reference_rgba, size)
    softened = ImageEnhance.Color(subject).enhance(1.06)
    canvas = Image.alpha_composite(background, _subject_shadow(softened, size, opacity=48, blur_radius=28, y_offset=18))
    return Image.alpha_composite(canvas, softened)


def _render_angled_view(reference_rgba, size):
    base = _cover_resize(reference_rgba, size)
    rotated = base.rotate(-7, resample=Image.Resampling.BICUBIC, expand=False)
    rotated = ImageEnhance.Contrast(rotated).enhance(1.1)
    background = Image.new("RGBA", size, "#121212")
    background = Image.alpha_composite(background, _radial_glow(size, "#4f3b2b", intensity=0.28))
    return Image.blend(background, rotated, 0.92)


def _linear_gradient(size, colors):
    start, end = colors
    gradient = Image.new("RGBA", size)
    top = Image.new("RGBA", (1, 1), start)
    bottom = Image.new("RGBA", (1, 1), end)
    for y in range(size[1]):
        ratio = y / max(1, size[1] - 1)
        pixel = Image.blend(top, bottom, ratio)
        row = pixel.resize((size[0], 1))
        gradient.paste(row, (0, y))
    return gradient


def _radial_glow(size, color, intensity=0.35):
    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    ellipse = Image.new("L", size, 0)
    mask_draw = Image.new("RGBA", size, (0, 0, 0, 0))
    cx, cy = size[0] // 2, int(size[1] * 0.36)
    max_radius_x = int(size[0] * 0.42)
    max_radius_y = int(size[1] * 0.28)
    for y in range(size[1]):
        for x in range(size[0]):
            dx = (x - cx) / max_radius_x
            dy = (y - cy) / max_radius_y
            distance = dx * dx + dy * dy
            if distance < 1:
                alpha = int((1 - distance) * 255 * intensity)
                ellipse.putpixel((x, y), alpha)
    fill = Image.new("RGBA", size, color)
    fill.putalpha(ellipse)
    return fill.filter(ImageFilter.GaussianBlur(46))


def _add_vignette(image, opacity):
    size = image.size
    vignette_mask = Image.new("L", size, 0)
    cx, cy = size[0] / 2, size[1] / 2
    max_distance = (cx * cx + cy * cy) ** 0.5
    for y in range(size[1]):
        for x in range(size[0]):
            distance = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            ratio = min(1.0, distance / max_distance)
            alpha = int((ratio ** 1.8) * 255 * opacity)
            vignette_mask.putpixel((x, y), alpha)
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    overlay.putalpha(vignette_mask)
    return Image.alpha_composite(image, overlay)


def _detail_focus(reference_rgba, size):
    target_aspect = size[0] / size[1]
    width, height = reference_rgba.size
    crop_width = int(width * 0.72)
    crop_height = int(crop_width / target_aspect)
    if crop_height > height:
        crop_height = int(height * 0.72)
        crop_width = int(crop_height * target_aspect)
    left = max(0, (width - crop_width) // 2)
    top = max(0, int((height - crop_height) * 0.32))
    box = (left, top, min(width, left + crop_width), min(height, top + crop_height))
    cropped = reference_rgba.crop(box)
    return _cover_resize(cropped, size)


def _render_shot(reference_rgba, shot):
    size = _parse_aspect_ratio(shot.get("aspect_ratio"))
    shot_name = (shot.get("name") or "").lower()
    prompt = (shot.get("prompt") or "").lower()
    combined = f"{shot_name} {prompt}"

    if "white" in combined or "studio" in combined:
        return _render_white_hero(reference_rgba, size)
    if "dark" in combined or "luxury" in combined:
        return _render_dark_hero(reference_rgba, size)
    if "macro" in combined or "detail" in combined or "close" in combined:
        return _render_detail_crop(reference_rgba, size)
    if "editorial" in combined or "soft" in combined or "portrait" in combined:
        return _render_soft_editorial(reference_rgba, size)
    if "angled" in combined:
        return _render_angled_view(reference_rgba, size)
    return _render_white_hero(reference_rgba, size)


def generate_free_image_candidates(draft):
    if Image is None:
        raise ProductAIError("Pillow is required to generate local image candidates.")
    if not draft.reference_image:
        raise ProductAIError("Add a reference image before generating image candidates.")
    if not draft.response_payload:
        raise ProductAIError("Generate the AI draft before creating image candidates.")

    draft.generated_images.all().delete()

    draft.reference_image.open("rb")
    try:
        reference = Image.open(draft.reference_image)
        reference.load()
    finally:
        draft.reference_image.close()

    reference_rgba = ImageOps.exif_transpose(reference).convert("RGBA")
    shots = _resolve_shots(draft.response_payload)
    created_images = []

    for index, shot in enumerate(shots[:4], start=1):
        rendered = _render_shot(reference_rgba, shot)
        output = BytesIO()
        rendered.convert("RGB").save(output, format="JPEG", quality=92, optimize=True)
        output.seek(0)

        slug = slugify(shot.get("name") or f"shot-{index}") or f"shot-{index}"
        upload = SimpleUploadedFile(
            f"{slug}.jpg",
            output.read(),
            content_type="image/jpeg",
        )
        created_images.append(
            draft.generated_images.create(
                image=upload,
                shot_name=shot.get("name") or f"Shot {index}",
                prompt=shot.get("prompt") or "",
                aspect_ratio=shot.get("aspect_ratio") or "1:1",
                sort_order=index,
            )
        )

    return created_images


def generate_product_ai_draft(*, image_bytes, mime_type, sku, price=None, vendor_hint=""):
    api_key = getattr(settings, "GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ProductAIError("GEMINI_API_KEY is not configured.")

    resolved_vendor_hint = (vendor_hint or "").strip() or infer_vendor_hint_from_sku(sku)

    payload = {
        "tools": [{"googleSearch": {}}],
        "contents": [
            {
                "parts": [
                    {"text": _prompt_for_product_enrichment(sku=sku, price=price, vendor_hint=resolved_vendor_hint)},
                    {
                        "inlineData": {
                            "mimeType": mime_type or "image/jpeg",
                            "data": base64.b64encode(image_bytes).decode("ascii"),
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.3,
        },
    }

    errors = []
    api_response = None
    models = _candidate_models()
    for model_name in models:
        query = urlencode({"key": api_key})
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?{query}"
        request = Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        for attempt in range(2):
            try:
                with urlopen(request, timeout=90) as response:
                    api_response = json.loads(response.read().decode("utf-8"))
                break
            except HTTPError as exc:
                details = exc.read().decode("utf-8", errors="ignore")
                errors.append(f"{model_name}: {exc.code} {details}")
                if exc.code in RETRYABLE_HTTP_STATUS_CODES and attempt == 0:
                    time.sleep(2)
                    continue
            except URLError as exc:
                errors.append(f"{model_name}: {exc.reason}")
            break

        if api_response is not None:
            break

    if api_response is None:
        raise ProductAIError(f"Gemini request failed: {' | '.join(errors)}")

    text = _extract_json_text(api_response)
    parsed = _normalize_payload(_safe_json_loads(text))

    sources = parsed["sources"]
    grounded_links = _extract_grounded_links(api_response)
    for link in grounded_links:
        if not any(source.get("url") == link["url"] for source in sources):
            sources.append(
                {
                    "title": link["title"],
                    "url": link["url"],
                    "match_type": "grounded",
                    "notes": "Returned by Gemini grounding metadata.",
                }
            )

    parsed["search_strategy"]["vendor_hint"] = parsed["search_strategy"].get("vendor_hint") or resolved_vendor_hint
    return parsed


def draft_to_product_initial(draft, *, categories=(), brands=()):
    payload = draft.response_payload or {}
    catalog_fields = payload.get("catalog_fields") or {}

    title = (catalog_fields.get("title") or "").strip()
    slug_hint = (catalog_fields.get("slug_hint") or "").strip()
    base_slug = slug_hint or title
    generated_slug = slugify(base_slug)[:160] if base_slug else ""
    if generated_slug and draft.sku:
        generated_slug = slugify(f"{generated_slug}-{draft.sku}")[:160]

    initial = {
        "title": title,
        "slug": generated_slug,
        "sku": draft.sku,
        "short_description": (catalog_fields.get("short_description") or "").strip(),
        "detail_description": (catalog_fields.get("detail_description") or "").strip(),
        "material": (catalog_fields.get("material") or "").strip(),
        "color": (catalog_fields.get("color") or "").strip(),
        "fit_notes": (catalog_fields.get("fit_notes") or "").strip(),
        "care_notes": (catalog_fields.get("care_notes") or "").strip(),
        "delivery_note": (catalog_fields.get("delivery_note") or "").strip(),
        "return_note": (catalog_fields.get("return_note") or "").strip(),
        "price": draft.price if draft.price is not None else "",
    }

    suggested_category = (catalog_fields.get("suggested_category") or "").strip().lower()
    for category in categories:
        if category.title.strip().lower() == suggested_category:
            initial["category"] = category.pk
            break

    suggested_brand = (catalog_fields.get("suggested_brand") or "").strip().lower()
    for brand in brands:
        if brand.title.strip().lower() == suggested_brand:
            initial["brand"] = brand.pk
            break

    return initial


def format_price_for_prompt(price):
    if price in (None, ""):
        return None
    if isinstance(price, Decimal):
        return price.quantize(Decimal("0.01"))
    return price
