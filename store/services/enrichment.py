"""Draft-enrichment state machine shared by dashboard views and background tasks."""
from django.utils import timezone

from store.ai_enrichment import (
    ProductAIError,
    apply_ai_draft_result,
    generate_product_ai_payload_for_draft,
)
from store.models import ProductAIDraft


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


def run_draft_enrichment(draft):
    """Run Gemini copy generation for a draft: analyzing -> ready / manual_review."""
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
    draft.processing_finished_at = timezone.now()
    draft.save(update_fields=["processing_finished_at", "updated_at"])
    return draft
