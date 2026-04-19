import base64
import json
import re
import socket
import time
from io import BytesIO
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.db import close_old_connections, connections
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
You are helping a local e-commerce merchandising team called Zentanee create a product draft from a single identifier image.

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
  "seo": {{
    "seo_title": "string",
    "meta_description": "string",
    "image_alt_text": "string",
    "focus_keyphrase": "string",
    "canonical_slug": "string"
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
  }},
  "generation_package": {{
    "mode": "reference-guided",
    "reference_strength": "high|medium|low",
    "notes": "string",
    "shots": [
      {{
        "name": "string",
        "prompt": "string",
        "negative_prompt": "string",
        "aspect_ratio": "1:1 or 4:5",
        "reference_images": ["primary", "secondary"],
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
        "seo": payload.get("seo") or {},
        "search_strategy": payload.get("search_strategy") or {},
        "confidence": payload.get("confidence") or {},
        "sources": payload.get("sources") or [],
        "image_plan": payload.get("image_plan") or {},
        "generation_package": payload.get("generation_package") or {},
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
    generation_package = payload.get("generation_package") or {}
    shots = generation_package.get("shots") or []
    if shots:
        return shots
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


def _blurred_backdrop(reference_rgba, size, *, brightness=0.85, blur=26, tint=None):
    backdrop = _cover_resize(reference_rgba, size)
    backdrop = backdrop.filter(ImageFilter.GaussianBlur(blur))
    backdrop = ImageEnhance.Brightness(backdrop).enhance(brightness)
    if tint:
        tint_layer = Image.new("RGBA", size, tint)
        backdrop = Image.blend(backdrop, tint_layer, 0.28)
    return backdrop


def _framed_photo(reference_rgba, size, *, scale=0.78, border=18, matte="#ffffff", inner_fill="#f7f3ee"):
    frame_width = int(size[0] * scale)
    frame_height = int(size[1] * scale)
    fitted = ImageOps.contain(
        reference_rgba,
        (max(20, frame_width - border * 2), max(20, frame_height - border * 2)),
        method=Image.Resampling.LANCZOS,
    )
    card = Image.new("RGBA", (frame_width, frame_height), inner_fill)
    inner_left = (frame_width - fitted.width) // 2
    inner_top = (frame_height - fitted.height) // 2
    card.alpha_composite(fitted, (inner_left, inner_top))
    return ImageOps.expand(card, border=border, fill=matte)


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
    background = Image.alpha_composite(background, _linear_gradient(size, ("#fffdfb", "#eee4d8")))
    card = _framed_photo(reference_rgba, size, scale=0.74, border=16, matte="#ffffff", inner_fill="#fbf8f3")
    card_canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    left = (size[0] - card.width) // 2
    top = (size[1] - card.height) // 2
    card_canvas.alpha_composite(card, (left, top))
    canvas = Image.alpha_composite(background, _subject_shadow(card_canvas, size, opacity=42, blur_radius=22, y_offset=16))
    return Image.alpha_composite(canvas, card_canvas)


def _render_dark_hero(reference_rgba, size):
    background = _blurred_backdrop(reference_rgba, size, brightness=0.38, blur=30, tint="#1b1622")
    background = Image.alpha_composite(background, _radial_glow(size, "#7f5f2e", intensity=0.22))
    card = _framed_photo(reference_rgba, size, scale=0.66, border=12, matte="#d9c8a0", inner_fill="#171412")
    card = ImageEnhance.Contrast(card).enhance(1.12)
    card = ImageEnhance.Color(card).enhance(1.05)
    card_canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    left = (size[0] - card.width) // 2
    top = (size[1] - card.height) // 2
    card_canvas.alpha_composite(card, (left, top))
    canvas = Image.alpha_composite(background, _subject_shadow(card_canvas, size, opacity=110, blur_radius=34, y_offset=24))
    return _add_vignette(Image.alpha_composite(canvas, card_canvas), 0.34)


def _render_detail_crop(reference_rgba, size):
    cropped = _detail_focus(reference_rgba, size)
    cropped = ImageEnhance.Sharpness(cropped).enhance(1.35)
    cropped = ImageEnhance.Contrast(cropped).enhance(1.08)
    return ImageOps.expand(cropped, border=18, fill="#ffffff")


def _render_soft_editorial(reference_rgba, size):
    background = _blurred_backdrop(reference_rgba, size, brightness=0.72, blur=34, tint="#d8ccd5")
    background = Image.alpha_composite(background, _linear_gradient(size, ("#f7f0ec", "#d8cbc7")))
    card = _framed_photo(reference_rgba, size, scale=0.62, border=20, matte="#fffaf6", inner_fill="#efe5dd")
    card = ImageEnhance.Color(card).enhance(1.08)
    card_canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    left = int(size[0] * 0.18)
    top = int(size[1] * 0.12)
    card_canvas.alpha_composite(card, (left, top))
    canvas = Image.alpha_composite(background, _subject_shadow(card_canvas, size, opacity=52, blur_radius=26, y_offset=20))
    return Image.alpha_composite(canvas, card_canvas)


def _render_angled_view(reference_rgba, size):
    background = _blurred_backdrop(reference_rgba, size, brightness=0.44, blur=32, tint="#211a16")
    card = _framed_photo(reference_rgba, size, scale=0.6, border=14, matte="#faf6f1", inner_fill="#151515")
    rotated = card.rotate(-8, resample=Image.Resampling.BICUBIC, expand=True)
    card_canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    left = (size[0] - rotated.width) // 2
    top = (size[1] - rotated.height) // 2
    card_canvas.alpha_composite(rotated, (left, top))
    canvas = Image.alpha_composite(background, _subject_shadow(card_canvas, size, opacity=96, blur_radius=30, y_offset=20))
    return _add_vignette(Image.alpha_composite(canvas, card_canvas), 0.22)


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


def _store_generated_candidate_images(draft, generated_items):
    connections.close_all()
    close_old_connections()
    draft.generated_images.all().delete()
    created_images = []
    for index, item in enumerate(generated_items[:6], start=1):
        if item.get("image_base64"):
            binary = base64.b64decode(item["image_base64"])
            filename = slugify(item.get("shot_name") or f"shot-{index}") or f"shot-{index}"
            upload = SimpleUploadedFile(
                f"{filename}.jpg",
                binary,
                content_type=item.get("content_type") or "image/jpeg",
            )
        elif item.get("image_url"):
            request = Request(item["image_url"], headers={"User-Agent": "Zentanee AI Draft"})
            with urlopen(request, timeout=90) as response:
                binary = response.read()
            filename = slugify(item.get("shot_name") or f"shot-{index}") or f"shot-{index}"
            upload = SimpleUploadedFile(
                f"{filename}.jpg",
                binary,
                content_type=item.get("content_type") or "image/jpeg",
            )
        else:
            continue

        created_images.append(
            draft.generated_images.create(
                image=upload,
                shot_name=item.get("shot_name") or f"Shot {index}",
                prompt=item.get("prompt") or "",
                aspect_ratio=item.get("aspect_ratio") or "1:1",
                sort_order=index,
            )
        )
        connections.close_all()
        close_old_connections()
    return created_images


def store_generated_candidate_images(draft, generated_items):
    return _store_generated_candidate_images(draft, generated_items)


def _chunk_list(items, chunk_size):
    chunk_size = max(1, int(chunk_size or 1))
    for index in range(0, len(items), chunk_size):
        yield items[index:index + chunk_size]


def _post_generator_payload(endpoint, payload, headers, *, timeout_seconds, max_attempts):
    last_timeout = None
    last_network_error = None

    for attempt in range(1, max_attempts + 1):
        request = Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="ignore")
            raise ProductAIError(f"Image generator failed: {exc.code} {details}") from exc
        except socket.timeout as exc:
            last_timeout = exc
            if attempt < max_attempts:
                time.sleep(2 * attempt)
                continue
        except URLError as exc:
            last_network_error = exc
            if attempt < max_attempts:
                time.sleep(2 * attempt)
                continue

    if last_timeout is not None:
        raise ProductAIError(
            "The hosted image generator took too long to respond. "
            "This usually means the free Hugging Face Space is still generating or waking up."
        ) from last_timeout
    if last_network_error is not None:
        raise ProductAIError(f"Image generator failed: {last_network_error.reason}") from last_network_error

    raise ProductAIError("Image generator failed without returning a response.")


def _call_external_generator(draft, *, base_url=""):
    endpoint = getattr(settings, "AI_IMAGE_GENERATOR_ENDPOINT", "").strip()
    if not endpoint:
        return None

    payload = build_generator_payload(draft, base_url=base_url)
    headers = {"Content-Type": "application/json"}
    auth_token = getattr(settings, "AI_IMAGE_GENERATOR_TOKEN", "").strip()
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    timeout_seconds = int(getattr(settings, "AI_IMAGE_GENERATOR_TIMEOUT", 300))
    max_attempts = int(getattr(settings, "AI_IMAGE_GENERATOR_RETRIES", 2))
    shots = payload.get("shots") or []
    shots_per_request = int(getattr(settings, "AI_IMAGE_GENERATOR_SHOTS_PER_REQUEST", 1))

    images = []
    for shot_batch in _chunk_list(shots, shots_per_request):
        batch_payload = dict(payload)
        batch_payload["shots"] = shot_batch
        body = _post_generator_payload(
            endpoint,
            batch_payload,
            headers,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
        )
        images.extend(body.get("images") or [])

    if not images:
        raise ProductAIError("Image generator returned no images.")
    return _store_generated_candidate_images(draft, images)


def _generate_local_image_candidates(draft):
    if Image is None:
        raise ProductAIError("Pillow is required to generate local image candidates.")
    if not draft.reference_image:
        raise ProductAIError("Add a reference image before generating image candidates.")
    if not draft.response_payload:
        raise ProductAIError("Generate the AI draft before creating image candidates.")

    draft.reference_image.open("rb")
    try:
        reference = Image.open(draft.reference_image)
        reference.load()
    finally:
        draft.reference_image.close()

    reference_rgba = ImageOps.exif_transpose(reference).convert("RGBA")
    shots = _resolve_shots(draft.response_payload)
    generated_items = []

    for index, shot in enumerate(shots[:4], start=1):
        rendered = _render_shot(reference_rgba, shot)
        output = BytesIO()
        rendered.convert("RGB").save(output, format="JPEG", quality=92, optimize=True)
        output.seek(0)

        generated_items.append(
            {
                "image_base64": base64.b64encode(output.read()).decode("ascii"),
                "content_type": "image/jpeg",
                "shot_name": shot.get("name") or f"Shot {index}",
                "prompt": shot.get("prompt") or "",
                "aspect_ratio": shot.get("aspect_ratio") or "1:1",
            }
        )

    return _store_generated_candidate_images(draft, generated_items)


def generate_reference_image_candidates(draft, *, base_url=""):
    fallback_to_local = str(getattr(settings, "AI_IMAGE_GENERATOR_FALLBACK_TO_LOCAL", "false")).lower() == "true"
    try:
        created = _call_external_generator(draft, base_url=base_url)
    except ProductAIError:
        if fallback_to_local:
            return _generate_local_image_candidates(draft)
        raise
    except Exception as exc:
        if fallback_to_local:
            return _generate_local_image_candidates(draft)
        raise ProductAIError(f"Image generator failed unexpectedly: {exc}") from exc

    if created is not None:
        return created
    return _generate_local_image_candidates(draft)


def generate_free_image_candidates(draft):
    return _generate_local_image_candidates(draft)


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


def generate_product_ai_payload_for_draft(draft):
    if not draft.reference_image:
        raise ProductAIError("Add a reference image before generating an AI draft.")

    draft.reference_image.open("rb")
    try:
        image_bytes = draft.reference_image.read()
        mime_type = getattr(draft.reference_image.file, "content_type", None) or "image/jpeg"
    finally:
        draft.reference_image.close()

    return generate_product_ai_draft(
        image_bytes=image_bytes,
        mime_type=mime_type,
        sku=draft.sku,
        price=format_price_for_prompt(draft.price),
        vendor_hint=draft.vendor_hint,
    )


def apply_ai_draft_result(
    draft,
    result,
    *,
    status=None,
    pipeline_state=None,
    error_message="",
    last_error_stage="",
):
    draft.vendor_hint = draft.vendor_hint or (result.get("search_strategy") or {}).get("vendor_hint", "")
    draft.response_payload = result
    draft.source_links = result.get("sources") or []
    draft.seo_payload = result.get("seo") or {}
    draft.image_plan = result.get("image_plan") or {}
    draft.generator_payload = result.get("generation_package") or {}
    draft.error_message = error_message
    draft.last_error_stage = last_error_stage
    if status:
        draft.status = status
    if pipeline_state:
        draft.pipeline_state = pipeline_state
    update_fields = [
        "vendor_hint",
        "response_payload",
        "source_links",
        "seo_payload",
        "image_plan",
        "generator_payload",
        "error_message",
        "last_error_stage",
        "updated_at",
    ]
    if status:
        update_fields.append("status")
    if pipeline_state:
        update_fields.append("pipeline_state")
    draft.save(update_fields=update_fields)
    return draft


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
        "seo_title": ((payload.get("seo") or {}).get("seo_title") or "").strip(),
        "seo_description": ((payload.get("seo") or {}).get("meta_description") or "").strip(),
        "image_alt_text": ((payload.get("seo") or {}).get("image_alt_text") or "").strip(),
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


def build_reference_image_payload(draft, *, base_url=""):
    references = []
    for label, field in (("primary", draft.reference_image), ("secondary", draft.secondary_reference_image)):
        if not field:
            continue
        url = field.url or ""
        if base_url and url.startswith("/"):
            url = f"{base_url.rstrip('/')}{url}"
        references.append(
            {
                "label": label,
                "url": url,
                "name": field.name,
            }
        )
    return references


def build_generator_payload(draft, *, base_url=""):
    payload = draft.response_payload or {}
    generation_package = payload.get("generation_package") or {}
    image_plan = payload.get("image_plan") or {}
    references = build_reference_image_payload(draft, base_url=base_url)
    shots = _resolve_shots(payload)

    return {
        "draft_id": draft.id,
        "sku": draft.sku,
        "vendor_hint": draft.vendor_hint,
        "product_title_hint": (payload.get("catalog_fields") or {}).get("title", ""),
        "reference_images": references,
        "reference_preservation_notes": image_plan.get("reference_preservation_notes", ""),
        "negative_prompt": image_plan.get("negative_prompt", ""),
        "mode": generation_package.get("mode") or "reference-guided",
        "reference_strength": generation_package.get("reference_strength") or "high",
        "notes": generation_package.get("notes") or "",
        "shots": [
            {
                "name": shot.get("name", ""),
                "prompt": shot.get("prompt", ""),
                "negative_prompt": shot.get("negative_prompt") or image_plan.get("negative_prompt", ""),
                "aspect_ratio": shot.get("aspect_ratio", "1:1"),
                "reference_images": shot.get("reference_images") or ["primary"],
                "priority": shot.get("priority", index + 1),
            }
            for index, shot in enumerate(shots)
        ],
    }
