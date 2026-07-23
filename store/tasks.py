"""Minimal database-backed task queue (outbox pattern).

No broker: `enqueue()` writes a `BackgroundTask` row, `run_pending()` drains
due rows. Run the drain via `manage.py run_tasks` (always-on hosting) or the
`POST /internal/run-tasks/` endpoint (serverless cron, shared-secret header).

With `settings.TASKS_EAGER = True` (default in DEBUG / tests) handlers execute
inline at enqueue time so local flows behave synchronously.
"""
import logging
import os
import time
from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
RETRY_BACKOFF_BASE_SECONDS = 60
RUN_TASKS_SECRET_HEADER = "X-Run-Tasks-Secret"


def _handle_telegram_product_post(payload):
    from store.services import telegram as telegram_service

    telegram_service.send_product_post(
        payload.get("product_id"),
        force=bool(payload.get("force")),
    )


def _handle_telegram_order_notify(payload):
    from store.services import telegram as telegram_service

    telegram_service.send_order_notification(payload)


def _handle_telegram_signup_notify(payload):
    from store.services import telegram as telegram_service

    telegram_service.send_signup_notification(payload)


def _handle_customer_order_confirm(payload):
    from store.services import telegram as telegram_service

    telegram_service.send_customer_order_confirmation(payload)


def _handle_customer_order_status(payload):
    from store.services import telegram as telegram_service

    telegram_service.send_customer_order_status(payload)


def _handle_customer_restock_notify(payload):
    from store.services import telegram as telegram_service

    telegram_service.send_customer_restock_notifications(payload)


def _handle_customer_abandoned_cart(payload):
    from store.services import telegram as telegram_service

    telegram_service.send_customer_abandoned_cart_nudge(payload)


def _handle_ai_enrich_draft(payload):
    from store.models import ProductAIDraft
    from store.services.enrichment import run_draft_enrichment

    draft = ProductAIDraft.objects.filter(pk=payload.get("draft_id")).first()
    if draft is None:
        return
    if draft.response_payload and draft.pipeline_state == ProductAIDraft.PIPELINE_READY:
        return  # Already enriched (duplicate enqueue).
    run_draft_enrichment(draft)


def _ai_enrich_permanent_failure(payload, error_text):
    """When the queue gives up on an enrichment task, surface it on the draft."""
    from store.models import ProductAIDraft
    from store.services.enrichment import mark_draft_manual_review

    draft = ProductAIDraft.objects.filter(pk=payload.get("draft_id")).first()
    if draft is None or draft.pipeline_state == ProductAIDraft.PIPELINE_MANUAL_REVIEW:
        return
    mark_draft_manual_review(draft, error_message=error_text, stage="task-queue")


def _registry():
    from store.models import BackgroundTask

    return {
        BackgroundTask.TYPE_TELEGRAM_PRODUCT_POST: _handle_telegram_product_post,
        BackgroundTask.TYPE_TELEGRAM_ORDER_NOTIFY: _handle_telegram_order_notify,
        BackgroundTask.TYPE_TELEGRAM_SIGNUP_NOTIFY: _handle_telegram_signup_notify,
        BackgroundTask.TYPE_AI_ENRICH_DRAFT: _handle_ai_enrich_draft,
        BackgroundTask.TYPE_CUSTOMER_ORDER_CONFIRM: _handle_customer_order_confirm,
        BackgroundTask.TYPE_CUSTOMER_ORDER_STATUS: _handle_customer_order_status,
        BackgroundTask.TYPE_CUSTOMER_RESTOCK_NOTIFY: _handle_customer_restock_notify,
        BackgroundTask.TYPE_CUSTOMER_ABANDONED_CART: _handle_customer_abandoned_cart,
    }


def _permanent_failure_hooks():
    from store.models import BackgroundTask

    return {
        BackgroundTask.TYPE_AI_ENRICH_DRAFT: _ai_enrich_permanent_failure,
    }


def enqueue(task_type, payload=None, run_after=None):
    """Queue a background task; executes inline when TASKS_EAGER is on."""
    from store.models import BackgroundTask

    task = BackgroundTask.objects.create(
        task_type=task_type,
        payload=payload or {},
        run_after=run_after or timezone.now(),
    )
    if getattr(settings, "TASKS_EAGER", False):
        execute(task)
    return task


def has_active_task(task_type, **payload_filters):
    from store.models import BackgroundTask

    queryset = BackgroundTask.objects.filter(
        task_type=task_type,
        status__in=(BackgroundTask.STATUS_PENDING, BackgroundTask.STATUS_RUNNING),
    )
    for key, value in payload_filters.items():
        queryset = queryset.filter(**{f"payload__{key}": value})
    return queryset.exists()


def execute(task):
    """Run one claimed task; returns True on success."""
    from store.models import BackgroundTask

    task.status = BackgroundTask.STATUS_RUNNING
    task.attempts += 1
    task.save(update_fields=["status", "attempts", "updated_at"])

    started = time.monotonic()
    try:
        handler = _registry()[task.task_type]
        handler(task.payload)
    except Exception as exc:  # noqa: BLE001 — queue must survive any handler error.
        duration = time.monotonic() - started
        task.last_error = f"{type(exc).__name__}: {exc}"[:2000]
        if task.attempts >= MAX_ATTEMPTS:
            task.status = BackgroundTask.STATUS_FAILED
            failure_hook = _permanent_failure_hooks().get(task.task_type)
            if failure_hook:
                try:
                    failure_hook(task.payload, task.last_error)
                except Exception:  # noqa: BLE001
                    logger.exception("Permanent-failure hook for %s crashed.", task.task_type)
        else:
            backoff = RETRY_BACKOFF_BASE_SECONDS * (2 ** (task.attempts - 1))
            task.status = BackgroundTask.STATUS_PENDING
            task.run_after = timezone.now() + timedelta(seconds=backoff)
        task.save(update_fields=["status", "last_error", "run_after", "updated_at"])
        logger.warning(
            "Task %s #%s failed in %.2fs (attempt %s/%s): %s",
            task.task_type, task.pk, duration, task.attempts, MAX_ATTEMPTS, task.last_error,
        )
        return False

    duration = time.monotonic() - started
    task.status = BackgroundTask.STATUS_DONE
    task.last_error = ""
    task.save(update_fields=["status", "last_error", "updated_at"])
    logger.info("Task %s #%s done in %.2fs.", task.task_type, task.pk, duration)
    return True


# Must comfortably exceed the longest legitimate handler run (enrichment can
# spend ~6 minutes across Gemini model fallbacks and retries), or the sweeper
# steals live tasks and double-executes them.
STALE_RUNNING_MINUTES = 15


def _requeue_stale_running():
    """Recover tasks stranded in RUNNING (e.g. the serverless function that
    claimed them was killed mid-flight) by putting them back in the queue."""
    from store.models import BackgroundTask

    cutoff = timezone.now() - timedelta(minutes=STALE_RUNNING_MINUTES)
    return BackgroundTask.objects.filter(
        status=BackgroundTask.STATUS_RUNNING,
        updated_at__lt=cutoff,
    ).update(status=BackgroundTask.STATUS_PENDING, run_after=timezone.now())


ORPHAN_DRAFT_GRACE_MINUTES = 2


def _enqueue_orphaned_ai_drafts():
    """Create tasks for queued AI drafts that have none.

    The queue page creates drafts in the "queued" state and relies on its own
    polling to start processing; if the tab closes before the first poll the
    draft would otherwise sit queued forever, because the cron drain only sees
    BackgroundTask rows.
    """
    from store.models import BackgroundTask, ProductAIDraft

    cutoff = timezone.now() - timedelta(minutes=ORPHAN_DRAFT_GRACE_MINUTES)
    created = 0
    orphan_candidates = ProductAIDraft.objects.filter(
        pipeline_state=ProductAIDraft.PIPELINE_QUEUED,
        updated_at__lt=cutoff,
    ).values_list("id", flat=True)
    for draft_id in orphan_candidates:
        if has_active_task(BackgroundTask.TYPE_AI_ENRICH_DRAFT, draft_id=draft_id):
            continue
        BackgroundTask.objects.create(
            task_type=BackgroundTask.TYPE_AI_ENRICH_DRAFT,
            payload={"draft_id": draft_id},
            run_after=timezone.now(),
        )
        created += 1
    return created


ABANDONED_CART_HOURS = 4


def _enqueue_abandoned_cart_nudges():
    """Queue one nudge per linked customer whose cart went quiet.

    A cart batch is "abandoned" when its newest row hasn't changed for
    ABANDONED_CART_HOURS. The handler re-checks state and stamps
    last_abandoned_nudge_at, so each cart state is nudged at most once.
    """
    from store.models import BackgroundTask, Cart, TelegramLink

    cutoff = timezone.now() - timedelta(hours=ABANDONED_CART_HOURS)
    created = 0
    for link in TelegramLink.objects.exclude(chat_id="").iterator():
        if link.user_id:
            cart_activity = Cart.objects.filter(user_id=link.user_id)
        else:
            cart_activity = Cart.objects.filter(user=None, session_key=link.session_key)
        latest = cart_activity.order_by("-updated_at").values_list("updated_at", flat=True).first()
        if latest is None or latest > cutoff:
            continue  # No cart, or still being edited.
        if link.last_abandoned_nudge_at and link.last_abandoned_nudge_at >= latest:
            continue  # This cart state was already nudged.
        if has_active_task(BackgroundTask.TYPE_CUSTOMER_ABANDONED_CART, link_id=link.id):
            continue
        BackgroundTask.objects.create(
            task_type=BackgroundTask.TYPE_CUSTOMER_ABANDONED_CART,
            payload={"link_id": link.id},
            run_after=timezone.now(),
        )
        created += 1
    return created


EVENT_RETENTION_DAYS = 90


def _purge_stale_product_events():
    """Keep the behavioral-event table bounded (recommendations only need
    recent history)."""
    from store.models import ProductEvent

    cutoff = timezone.now() - timedelta(days=EVENT_RETENTION_DAYS)
    deleted, _ = ProductEvent.objects.filter(created_at__lt=cutoff).delete()
    return deleted


def run_pending(limit=10):
    """Claim and execute due tasks; returns the number of tasks executed."""
    from store.models import BackgroundTask

    _requeue_stale_running()
    _enqueue_orphaned_ai_drafts()
    _enqueue_abandoned_cart_nudges()
    _purge_stale_product_events()

    claim_kwargs = {}
    if connection.features.has_select_for_update_skip_locked:
        claim_kwargs["skip_locked"] = True

    with transaction.atomic():
        claimed = list(
            BackgroundTask.objects.select_for_update(**claim_kwargs)
            .filter(status=BackgroundTask.STATUS_PENDING, run_after__lte=timezone.now())
            .order_by("run_after", "id")[:limit]
        )
        if claimed:
            # .update() bypasses auto_now, so stamp updated_at explicitly —
            # the stale-RUNNING sweeper measures staleness from it, and a
            # claimed-but-not-yet-executed task (later in this batch) must not
            # look abandoned to a concurrent drain.
            BackgroundTask.objects.filter(pk__in=[task.pk for task in claimed]).update(
                status=BackgroundTask.STATUS_RUNNING,
                updated_at=timezone.now(),
            )

    for task in claimed:
        execute(task)
    return len(claimed)


def retry_task(task):
    """Requeue a failed task for a fresh round of attempts."""
    from store.models import BackgroundTask

    task.status = BackgroundTask.STATUS_PENDING
    task.attempts = 0
    task.run_after = timezone.now()
    task.save(update_fields=["status", "attempts", "run_after", "updated_at"])
    if getattr(settings, "TASKS_EAGER", False):
        execute(task)
    return task


@csrf_exempt
def run_tasks_endpoint(request):
    """HTTP drain trigger for serverless cron (guarded by a shared secret).

    Accepts the secret either in the `X-Run-Tasks-Secret` header or as a
    bearer token (`Authorization: Bearer <secret>`), matching Vercel Cron's
    CRON_SECRET convention. GET is allowed because Vercel Cron only sends GET.
    """
    if request.method not in ("POST", "GET"):
        return HttpResponse(status=405)

    expected_secret = (os.getenv("RUN_TASKS_SECRET") or os.getenv("CRON_SECRET") or "").strip()
    provided_secret = request.headers.get(RUN_TASKS_SECRET_HEADER, "").strip()
    if not provided_secret:
        authorization = request.headers.get("Authorization", "").strip()
        if authorization.startswith("Bearer "):
            provided_secret = authorization[len("Bearer "):].strip()

    if not expected_secret:
        if not settings.DEBUG:
            return HttpResponse(status=403)
    elif provided_secret != expected_secret:
        return HttpResponse(status=403)

    try:
        limit = max(1, min(int(request.GET.get("limit", 10)), 50))
    except (TypeError, ValueError):
        limit = 10
    processed = run_pending(limit=limit)
    return JsonResponse({"ok": True, "processed": processed})
