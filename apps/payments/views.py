import hashlib

from django.contrib.auth.decorators import login_required, permission_required, user_passes_test
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.ledger.models import LedgerEntry
from apps.ledger.services import LedgerService

from .forms import ReceiptReviewForm, ReceiptUploadForm, ReconciliationUploadForm
from .models import PaymentProof, ReconciliationRun
from .reconciliation import ReconciliationError, ReconciliationService
from .services import WebhookService, get_client_ip


@csrf_exempt
@require_POST
def payvessel_webhook_view(request):
    """
    No CSRF (external caller, no session), no auth decorator — PayVessel
    authenticates itself via the HMAC signature, verified inside
    WebhookService. If an unexpected exception propagates from the
    service (see its docstring), Django returns a 500 automatically here,
    which is what makes PayVessel retry the delivery — that's intentional,
    not an oversight.
    """
    raw_body = request.body  # MUST be read before anything touches request.POST
    signature = request.META.get("HTTP_PAYVESSEL_HTTP_SIGNATURE", "")
    remote_ip = get_client_ip(request)

    status, message = WebhookService.process_payvessel_webhook(
        raw_body=raw_body, signature_header=signature, remote_ip=remote_ip
    )
    return JsonResponse({"message": message}, status=status)


@login_required
def receipt_upload_view(request):
    """Member-facing upload (Section 5c) — no OCR, no extraction, just a file and what the member claims it is."""
    if request.method == "POST":
        form = ReceiptUploadForm(request.POST, request.FILES)
        if form.is_valid():
            proof = form.save(commit=False)
            proof.member = request.user

            file_bytes = proof.file.read()
            proof.file_hash = hashlib.sha256(file_bytes).hexdigest()
            proof.file.seek(0)

            is_duplicate = (
                PaymentProof.objects.filter(file_hash=proof.file_hash)
                .exclude(status=PaymentProof.Status.REJECTED)
                .exists()
            )
            proof.status = PaymentProof.Status.POSSIBLE_DUPLICATE if is_duplicate else PaymentProof.Status.PENDING_REVIEW
            proof.save()
            return redirect("payments:receipt_upload")
    else:
        form = ReceiptUploadForm()

    my_proofs = PaymentProof.objects.filter(member=request.user).order_by("-uploaded_at")[:10]
    return render(request, "payments/receipt_upload.html", {"form": form, "my_proofs": my_proofs})


def _is_admin_tier(user):
    return user.is_authenticated and user.is_admin_tier


@login_required
@user_passes_test(_is_admin_tier)
@permission_required("payments.change_paymentproof", raise_exception=True)
def receipt_review_queue_view(request):
    proofs = (
        PaymentProof.objects.filter(
            status__in=[PaymentProof.Status.PENDING_REVIEW, PaymentProof.Status.POSSIBLE_DUPLICATE]
        )
        .select_related("member")
        .order_by("-uploaded_at")
    )
    return render(request, "payments/receipt_review_queue.html", {"proofs": proofs})


@login_required
@user_passes_test(_is_admin_tier)
@permission_required("payments.change_paymentproof", raise_exception=True)
def receipt_review_detail_view(request, pk):
    proof = get_object_or_404(PaymentProof, pk=pk)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "approve":
            form = ReceiptReviewForm(request.POST)
            if form.is_valid():
                entry = LedgerService.post_savings_entry(
                    member=proof.member,
                    entry_type=form.cleaned_data["entry_type"],
                    amount=form.cleaned_data["amount"],
                    source=LedgerEntry.Source.RECEIPT_UPLOAD,
                    created_by=request.user,
                    note=f"Reviewed receipt #{proof.pk}",
                )
                proof.status = PaymentProof.Status.CONFIRMED
                proof.reviewed_by = request.user
                proof.reviewed_at = timezone.now()
                proof.resulting_ledger_entry = entry
                proof.save()
                return redirect("payments:receipt_review_queue")
        elif action == "reject":
            reason = request.POST.get("rejection_reason", "").strip()
            if not reason:
                form = ReceiptReviewForm(
                    initial={"entry_type": proof.claimed_type, "amount": proof.claimed_amount}
                )
                return render(
                    request,
                    "payments/receipt_review_detail.html",
                    {"proof": proof, "form": form, "error": "A rejection reason is required."},
                )
            proof.status = PaymentProof.Status.REJECTED
            proof.reviewed_by = request.user
            proof.reviewed_at = timezone.now()
            proof.rejection_reason = reason
            proof.save()
            return redirect("payments:receipt_review_queue")

    form = ReceiptReviewForm(initial={"entry_type": proof.claimed_type, "amount": proof.claimed_amount})
    return render(request, "payments/receipt_review_detail.html", {"proof": proof, "form": form})


@login_required
@user_passes_test(_is_admin_tier)
@permission_required("payments.add_reconciliationrun", raise_exception=True)
def reconciliation_upload_view(request):
    """
    Section 3B/7 reconciliation tool. See ReconciliationRun's docstring
    for why this is a CSV upload rather than a direct PayVessel API call —
    their settlement-export endpoint wasn't confirmed against the docs
    fetched for this build.
    """
    if request.method == "POST":
        form = ReconciliationUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                run = ReconciliationService.run(csv_file=form.cleaned_data["csv_file"], admin=request.user)
                return redirect("payments:reconciliation_result", run.pk)
            except ReconciliationError as exc:
                form.add_error("csv_file", str(exc))
    else:
        form = ReconciliationUploadForm()

    past_runs = ReconciliationRun.objects.select_related("uploaded_by")[:20]
    return render(request, "payments/reconciliation_upload.html", {"form": form, "past_runs": past_runs})


@login_required
@user_passes_test(_is_admin_tier)
@permission_required("payments.add_reconciliationrun", raise_exception=True)
def reconciliation_result_view(request, pk):
    run = get_object_or_404(ReconciliationRun, pk=pk)
    discrepancies = run.discrepancies.all()
    return render(request, "payments/reconciliation_result.html", {"run": run, "discrepancies": discrepancies})
