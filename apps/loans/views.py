from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required, user_passes_test
from django.shortcuts import get_object_or_404, redirect, render

from apps.ledger.models import LedgerEntry
from apps.ledger.services import LedgerService

from .eligibility import EligibilityService
from .forms import LoanApplicationForm, LoanRejectionForm, RecordRepaymentForm
from .models import Loan
from .services import LoanError, LoanService


def _is_admin_tier(user):
    return user.is_authenticated and user.is_admin_tier


@login_required
def apply_for_loan_view(request):
    if request.method == "POST":
        form = LoanApplicationForm(request.POST, applicant=request.user)
        if form.is_valid():
            try:
                LoanService.apply_for_loan(
                    member=request.user,
                    policy=form.cleaned_data["policy"],
                    principal=form.cleaned_data["principal"],
                    tenure_months=form.cleaned_data["tenure_months"],
                    purpose=form.cleaned_data["purpose"],
                    guarantor=form.cleaned_data["guarantor"],
                )
                return redirect("loans:my_loans")
            except LoanError as exc:
                # Covers both ordinary validation errors and an
                # IneligibleError re-raised by LoanService — either way,
                # the member sees the reason in plain terms (Section 6).
                form.add_error(None, str(exc))
    else:
        form = LoanApplicationForm(applicant=request.user)

    eligibility = EligibilityService.snapshot(request.user)
    return render(request, "loans/apply.html", {"form": form, "eligibility": eligibility})


@login_required
def my_loans_view(request):
    loans = request.user.loans.all()
    guarantor_requests = request.user.guaranteed_loans.filter(status=Loan.Status.GUARANTOR_PENDING)
    return render(request, "loans/my_loans.html", {"loans": loans, "guarantor_requests": guarantor_requests})


@login_required
def loan_detail_view(request, pk):
    loan = get_object_or_404(Loan, pk=pk, member=request.user)
    schedule = loan.repayment_schedule.all()
    outstanding = LedgerService.get_loan_outstanding_balance(loan) if loan.status in (Loan.Status.ACTIVE, Loan.Status.COMPLETED) else None
    return render(request, "loans/loan_detail.html", {"loan": loan, "schedule": schedule, "outstanding": outstanding})


@login_required
def respond_to_guarantor_request_view(request, pk):
    loan = get_object_or_404(Loan, pk=pk, guarantor=request.user, status=Loan.Status.GUARANTOR_PENDING)
    if request.method == "POST":
        accept = request.POST.get("action") == "accept"
        try:
            LoanService.respond_to_guarantor_request(loan=loan, guarantor=request.user, accept=accept)
        except LoanError:
            pass  # form is re-shown; loan.status will reflect why nothing changed
        return redirect("loans:my_loans")
    return render(request, "loans/guarantor_request.html", {"loan": loan})


@login_required
@user_passes_test(_is_admin_tier)
@permission_required("loans.can_review_loans", raise_exception=True)
def loan_queue_view(request):
    # Only PENDING loans need admin action; GUARANTOR_PENDING is the
    # member's / guarantor's responsibility until the guarantor responds
    # (admin queue would just show loans they can't act on yet).
    loans = Loan.objects.filter(status=Loan.Status.PENDING).select_related("member", "policy")
    return render(request, "loans/admin_queue.html", {"loans": loans})


@login_required
@user_passes_test(_is_admin_tier)
@permission_required("loans.can_review_loans", raise_exception=True)
def loan_review_view(request, pk):
    loan = get_object_or_404(Loan.objects.select_related("member", "policy"), pk=pk)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "approve":
            try:
                LoanService.approve_loan(loan=loan, admin=request.user)
                messages.success(request, f"Loan #{loan.pk} approved. You can disburse it from the queue.")
                return redirect("loans:admin_queue")
            except LoanError as exc:
                return render(request, "loans/admin_review.html", {"loan": loan, "rejection_form": LoanRejectionForm(), "error": str(exc)})
        elif action == "reject":
            rejection_form = LoanRejectionForm(request.POST)
            if rejection_form.is_valid():
                LoanService.reject_loan(loan=loan, admin=request.user, reason=rejection_form.cleaned_data["reason"])
                messages.success(request, f"Loan #{loan.pk} rejected.")
                return redirect("loans:admin_queue")
            return render(request, "loans/admin_review.html", {"loan": loan, "rejection_form": rejection_form})
        elif action == "disburse":
            try:
                LoanService.disburse_loan(loan=loan, admin=request.user)
                messages.success(request, f"Loan #{loan.pk} disbursed and schedule generated.")
                return redirect("loans:admin_queue")
            except LoanError as exc:
                return render(request, "loans/admin_review.html", {"loan": loan, "rejection_form": LoanRejectionForm(), "error": str(exc)})

    return render(request, "loans/admin_review.html", {"loan": loan, "rejection_form": LoanRejectionForm()})


@login_required
@user_passes_test(_is_admin_tier)
@permission_required("ledger.can_record_manual_transaction", raise_exception=True)
def record_repayment_view(request, pk):
    """
    Admin-facing fallback for recording a loan repayment with no attached
    receipt/webhook ("Manual transaction entry"), scoped to a
    specific loan. Payment via PayVessel webhook / receipt upload
    currently always posts as a savings deposit (see payments/services.py
    docstring) — routing a webhook or receipt-uploaded payment to a
    specific loan's repayment stream is a reasonable follow-up, flagged
    here rather than silently assumed to already work.
    """
    loan = get_object_or_404(Loan, pk=pk, status=Loan.Status.ACTIVE)
    if request.method == "POST":
        form = RecordRepaymentForm(request.POST)
        if form.is_valid():
            try:
                LoanService.record_repayment(
                    loan=loan,
                    amount=form.cleaned_data["amount"],
                    source=LedgerEntry.Source.MANUAL,
                    created_by=request.user,
                    note=form.cleaned_data["note"],
                )
                return redirect("loans:admin_queue")
            except LoanError as exc:
                return render(request, "loans/record_repayment.html", {"loan": loan, "form": form, "error": str(exc)})
    else:
        form = RecordRepaymentForm()
    return render(request, "loans/record_repayment.html", {"loan": loan, "form": form})
