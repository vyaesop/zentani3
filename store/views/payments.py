"""Chapa return and webhook endpoints.

Neither endpoint trusts what it is told: both call Chapa's verify API before
marking an order paid, and the webhook additionally requires a valid signature.
"""
import json
import logging

from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from store.models import OrderGroup
from store.payments import chapa
from store.services.checkout import mark_group_paid

logger = logging.getLogger(__name__)


def _group_for_tx_ref(tx_ref):
    """tx_ref is `<number>-<id>`; the id is authoritative, the number a check."""
    if not tx_ref or "-" not in tx_ref:
        return None
    number, _, group_id = tx_ref.rpartition("-")
    if not group_id.isdigit():
        return None
    return OrderGroup.objects.filter(pk=int(group_id), number=number).first()


def _settle(group, tx_ref):
    """Verify with Chapa and mark paid. Returns True when the order is paid."""
    if group.payment_status == OrderGroup.PAYMENT_PAID:
        return True
    try:
        verified = chapa.verify_payment(tx_ref)
    except chapa.ChapaError as exc:
        logger.info("Chapa verify for %s not settled: %s", tx_ref, exc)
        return False
    if not chapa.payment_matches(group, verified):
        logger.warning("Chapa payment %s does not match order %s totals.", tx_ref, group.number)
        return False
    mark_group_paid(group, reference=str(verified.get("reference") or tx_ref))
    return True


@require_GET
def chapa_return(request):
    tx_ref = (request.GET.get("tx_ref") or request.GET.get("trx_ref") or "").strip()
    group = _group_for_tx_ref(tx_ref)
    if group is None:
        messages.error(request, "We could not match that payment to an order.")
        return redirect("store:home")

    if _settle(group, tx_ref):
        messages.success(request, f"Payment received — order {group.number} is confirmed and will be dispatched first.")
    else:
        messages.warning(
            request,
            f"We have not received the payment for {group.number} yet. If you completed it, it will update shortly; "
            "otherwise the order stays as cash on delivery.",
        )
    return redirect("store:order-confirmation", token=group.claim_token)


@csrf_exempt
@require_POST
def chapa_webhook(request):
    if not chapa.webhook_signature_valid(request.body, request.headers):
        return HttpResponse(status=403)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except ValueError:
        return JsonResponse({"ok": False, "error": "invalid-json"}, status=400)

    tx_ref = str(payload.get("tx_ref") or payload.get("trx_ref") or "").strip()
    group = _group_for_tx_ref(tx_ref)
    if group is None:
        return JsonResponse({"ok": False, "error": "unknown-order"}, status=404)

    paid = _settle(group, tx_ref)
    return JsonResponse({"ok": True, "paid": paid})
