"""Draft-enrichment state machine shared by dashboard views and background tasks."""
import os

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from store.ai_enrichment import (
    ProductAIError,
    apply_ai_draft_result,
    draft_to_product_initial,
    generate_product_ai_payload_for_draft,
    match_taxonomy,
    taxonomy_creation_proposal,
    _normalize_taxonomy_label,
)
from store.models import Brand, Category, Product, ProductAIDraft, ProductImages


def mark_draft_manual_review(draft, *, error_message, stage):
    draft.status = ProductAIDraft.STATUS_FAILED
    draft.pipeline_state = ProductAIDraft.PIPELINE_MANUAL_REVIEW
    draft.error_message = str(error_message)[:250]
    draft.last_error_stage = stage
    draft.processing_finished_at = timezone.now()
    draft.save(
        update_fields=[
            "status",
            "pipeline_state",
            "error_message",
            "last_error_stage",
            "processing_finished_at",
            "updated_at",
        ]
    )
    return draft


def _unique_taxonomy_slug(model, base):
    slug_base = slugify(base)[:50] or "collection"
    candidate = slug_base
    suffix = 2
    while model.objects.filter(slug=candidate).exists():
        candidate = f"{slug_base[:45]}-{suffix}"
        suffix += 1
    return candidate


def _find_existing_by_label(model, label):
    wanted = _normalize_taxonomy_label(label)
    if not wanted:
        return None
    for row in model.objects.all():
        title_label = _normalize_taxonomy_label(row.title)
        slug_label = _normalize_taxonomy_label((row.slug or "").replace("-", " "))
        if wanted in {title_label, title_label.rstrip("s"), slug_label, slug_label.rstrip("s")} or wanted.rstrip("s") in {title_label, slug_label}:
            return row
    return None


def _resolve_taxonomy_for_draft(draft, kind):
    """Resolve a draft's collection/brand: match an existing row first; create a
    new one only when Gemini found no fit AND is highly confident AND the
    matching AI_AUTO_CREATE_* setting allows it. Returns (instance, note)."""
    model = Category if kind == "collection" else Brand
    allow_create = (
        settings.AI_AUTO_CREATE_COLLECTIONS if kind == "collection" else settings.AI_AUTO_CREATE_BRANDS
    )
    label = "collection" if kind == "collection" else "brand"
    payload = draft.response_payload or {}

    matched = match_taxonomy(payload, kind, model.objects.filter(is_active=True))
    if matched is not None:
        return matched, ""

    proposal = taxonomy_creation_proposal(payload, kind)
    if not proposal:
        return None, f"No confident {label} match — pick one manually."
    if not allow_create:
        return None, f'Gemini proposed a new {label} "{proposal}", but automatic creation is disabled.'

    # Never duplicate: reuse any existing row (active or not) whose name already
    # covers the proposal.
    existing = _find_existing_by_label(model, proposal)
    if existing is not None:
        return existing, ""

    created = model.objects.create(
        title=proposal[:50],
        slug=_unique_taxonomy_slug(model, proposal),
        description="Created automatically from an AI product draft.",
        is_active=True,
        is_featured=False,
    )
    return created, f'Created new {label} "{created.title}".'


def _copy_field_file(field_file):
    """Read an ImageField's bytes into a ContentFile for reuse on another model."""
    field_file.open("rb")
    try:
        content = field_file.read()
    finally:
        field_file.close()
    return ContentFile(content, name=os.path.basename(field_file.name))


def create_product_from_draft(draft):
    """Turn a ready AI draft into an unpublished Product with images attached.

    Returns (product, created, notes). Never raises for business-rule misses —
    the notes explain why creation was skipped so the dashboard can surface it.
    """
    notes = []
    if draft.product_id:
        return draft.product, False, notes

    payload = draft.response_payload or {}
    catalog_fields = payload.get("catalog_fields") or {}
    if not catalog_fields:
        return None, False, ["The draft has no AI copy yet."]
    if draft.price is None:
        return None, False, ["Add a price to the draft before it can become a product."]
    if not (draft.cover_image or draft.reference_image):
        return None, False, ["Add a cover image (or reference image) before the product can be created."]
    if Product.objects.filter(sku=draft.sku).exists():
        return None, False, [f'A product with SKU "{draft.sku}" already exists — open it instead.']

    category, category_note = _resolve_taxonomy_for_draft(draft, "collection")
    if category_note:
        notes.append(category_note)
    if category is None:
        return None, False, notes

    brand, brand_note = _resolve_taxonomy_for_draft(draft, "brand")
    if brand_note:
        notes.append(brand_note)

    initial = draft_to_product_initial(draft, categories=[category], brands=[brand] if brand else [])
    title = (initial.get("title") or draft.sku)[:150]
    slug = (initial.get("slug") or slugify(f"{title}-{draft.sku}"))[:160] or slugify(draft.sku)[:160]

    cover_source = draft.cover_image or draft.reference_image
    cover_file = _copy_field_file(cover_source)

    from store.telegram_notify import suspend_telegram_autopublish

    with transaction.atomic():
        with suspend_telegram_autopublish():
            product = Product(
                title=title,
                slug=slug,
                sku=draft.sku,
                short_description=initial.get("short_description") or title,
                seo_title=(initial.get("seo_title") or "")[:180],
                seo_description=(initial.get("seo_description") or "")[:320],
                image_alt_text=(initial.get("image_alt_text") or title)[:180],
                detail_description=initial.get("detail_description") or "",
                material=(initial.get("material") or "")[:120],
                color=(initial.get("color") or "")[:80],
                fit_notes=initial.get("fit_notes") or "",
                care_notes=initial.get("care_notes") or "",
                price=draft.price,
                category=category,
                brand=brand,
                is_active=False,
                is_featured=False,
                is_sold_out=False,
            )
            product.product_image.save(cover_file.name, cover_file, save=False)
            product.save()

            for upload in draft.gallery_uploads.all():
                gallery_file = _copy_field_file(upload.image)
                gallery_image = ProductImages(product=product)
                gallery_image.image.save(gallery_file.name, gallery_file, save=False)
                gallery_image.save()

            draft.product = product
            draft.save(update_fields=["product", "updated_at"])

    return product, True, notes


def _record_draft_automation(draft, *, product, created, notes):
    """Persist the auto-creation outcome on the draft payload for the dashboard."""
    payload = dict(draft.response_payload or {})
    payload["automation"] = {
        "product_created": created,
        "product_id": product.id if product else None,
        "notes": notes,
    }
    draft.response_payload = payload
    draft.save(update_fields=["response_payload", "updated_at"])


def run_draft_enrichment(draft):
    """Run Gemini copy generation for a draft: analyzing -> ready / manual_review.

    On success the draft is also turned into an unpublished product (with the
    intake cover/gallery images attached) so publishing is one click away.
    """
    draft.pipeline_state = ProductAIDraft.PIPELINE_ANALYZING
    draft.processing_started_at = timezone.now()
    draft.processing_finished_at = None
    draft.attempt_count += 1
    draft.error_message = ""
    draft.last_error_stage = ""
    draft.save(
        update_fields=[
            "pipeline_state",
            "processing_started_at",
            "processing_finished_at",
            "attempt_count",
            "error_message",
            "last_error_stage",
            "updated_at",
        ]
    )

    try:
        result = generate_product_ai_payload_for_draft(draft)
    except ProductAIError as exc:
        return mark_draft_manual_review(draft, error_message=exc, stage="content")

    apply_ai_draft_result(
        draft,
        result,
        status=ProductAIDraft.STATUS_SUCCEEDED,
        pipeline_state=ProductAIDraft.PIPELINE_READY,
        error_message="",
        last_error_stage="",
    )

    # Act on Gemini's taxonomy verdict right away, even if the product itself
    # can't be created yet (e.g. a business-rule miss further down): a
    # high-confidence "nothing fits" proposal creates the collection/brand now,
    # so the prefilled form and any later pass find it in place.
    taxonomy_notes = []
    for kind in ("collection", "brand"):
        try:
            _, taxonomy_note = _resolve_taxonomy_for_draft(draft, kind)
        except Exception as exc:  # noqa: BLE001 — enrichment result must survive.
            taxonomy_note = f"Could not resolve the {kind}: {exc}"
        if taxonomy_note:
            taxonomy_notes.append(taxonomy_note)

    try:
        product, created, notes = create_product_from_draft(draft)
    except Exception as exc:  # noqa: BLE001 — copy succeeded; creation failure must not lose it.
        product, created, notes = None, False, [f"Automatic product creation failed: {exc}"]
    merged_notes = taxonomy_notes + [note for note in notes if note not in taxonomy_notes]
    _record_draft_automation(draft, product=product, created=created, notes=merged_notes)

    draft.processing_finished_at = timezone.now()
    draft.save(update_fields=["processing_finished_at", "updated_at"])
    return draft
