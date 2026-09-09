"""
LoanService is the sanctioned entry point for every loan lifecycle
transition. Like LedgerService, no view/task should mutate a Loan's
status or post loan money movement directly — go through here so every
transition is validated and (where money moves) posted via LedgerService.

apply_for_loan() now enforces Shared Capital / tenure /
savings-threshold eligibility via EligibilityService, gated by the
django-waffle switch — see eligibility.py. This is exactly the extension
point flagged in the previous build: nothing else in this file changed.
"""

from django.db import transaction
from django.utils import timezone

from apps.ledger.models import LedgerEntry
from apps.ledger.services import LedgerService

from .eligibility import EligibilityService, IneligibleError
from .models import Loan, RepaymentSchedule


class LoanError(Exception):
    pass


class LoanService:
    @staticmethod
    def apply_for_loan(*, member, policy, principal, tenure_months, purpose, guarantor=None):
        if principal <= 0:
            raise LoanError("principal must be positive.")
        if tenure_months <= 0:
            raise LoanError("tenure_months must be positive.")
        
        # Block re-application while any earlier loan is still open.
        # APPROVED counts because disbursement is imminent; DISBURSED is the
        # transient state between approved and active (schedule generated).
        # ACTIVE / DEFAULTED are the obvious cases. COMPLETED is excluded —
        # once a loan is fully repaid the gate clears.
        open_statuses = (
            Loan.Status.APPROVED,
            Loan.Status.DISBURSED,
            Loan.Status.ACTIVE,
            Loan.Status.DEFAULTED,
        )
        if Loan.objects.filter(member=member, status__in=open_statuses).exists():
            raise LoanError(
                "You already have a loan that hasn't been fully repaid. "
                "Finish repaying your existing loan before applying for a new one."
            )

        try:
            EligibilityService.check(member=member, policy=policy, principal=principal)
        except IneligibleError as exc:
            # Re-raised as LoanError so callers only need to catch one
            # exception type from this service — the plain-language reason
            # ("member sees why in plain terms") passes through
            # unchanged.
            raise LoanError(str(exc)) from exc

        loan = Loan.objects.create(
            member=member,
            policy=policy,
            principal=principal,
            tenure_months=tenure_months,
            purpose=purpose,
            guarantor=guarantor,
            status=Loan.Status.GUARANTOR_PENDING if guarantor else Loan.Status.PENDING,
        )
        return loan

    @staticmethod
    def respond_to_guarantor_request(*, loan: Loan, guarantor, accept: bool):
        if loan.guarantor_id != guarantor.pk:
            raise LoanError("This user is not the guarantor for this loan.")
        if loan.status != Loan.Status.GUARANTOR_PENDING:
            raise LoanError("This loan is not awaiting a guarantor response.")

        if accept:
            loan.guarantor_accepted_at = timezone.now()
            loan.status = Loan.Status.PENDING
            loan.save(update_fields=["guarantor_accepted_at", "status"])
        else:
            loan.guarantor_declined_at = timezone.now()
            loan.status = Loan.Status.REJECTED
            loan.rejection_reason = "Guarantor declined to guarantee this loan."
            loan.save(update_fields=["guarantor_declined_at", "status", "rejection_reason"])
        return loan

    @staticmethod
    def approve_loan(*, loan: Loan, admin):
        if loan.status != Loan.Status.PENDING:
            raise LoanError(f"Cannot approve a loan in status '{loan.status}'.")
        loan.status = Loan.Status.APPROVED
        loan.reviewed_by = admin
        loan.reviewed_at = timezone.now()
        loan.save(update_fields=["status", "reviewed_by", "reviewed_at"])
        return loan

    @staticmethod
    def reject_loan(*, loan: Loan, admin, reason):
        if not reason or not reason.strip():
            raise LoanError("A rejection reason is required.")
        if loan.status not in (Loan.Status.PENDING, Loan.Status.GUARANTOR_PENDING):
            raise LoanError(f"Cannot reject a loan in status '{loan.status}'.")
        loan.status = Loan.Status.REJECTED
        loan.reviewed_by = admin
        loan.reviewed_at = timezone.now()
        loan.rejection_reason = reason
        loan.save(update_fields=["status", "reviewed_by", "reviewed_at", "rejection_reason"])
        return loan

    @staticmethod
    @transaction.atomic
    def disburse_loan(*, loan: Loan, admin, source=LedgerEntry.Source.MANUAL):
        """
        Posts the loan_disbursement ledger entry, generates the repayment
        schedule, and marks the loan active — all in one transaction, so a
        failure partway (e.g. schedule generation) doesn't leave a
        disbursed-but-unscheduled loan.
        """
        if loan.status != Loan.Status.APPROVED:
            raise LoanError(f"Cannot disburse a loan in status '{loan.status}'.")

        LedgerService.post_loan_entry(
            loan=loan,
            entry_type=LedgerEntry.EntryType.LOAN_DISBURSEMENT,
            amount=loan.total_repayable,
            source=source,
            created_by=admin,
            note=f"Disbursement of loan #{loan.pk}",
        )
        loan.generate_repayment_schedule()

        loan.status = Loan.Status.ACTIVE
        loan.disbursed_at = timezone.now()
        loan.save(update_fields=["status", "disbursed_at"])
        return loan

    @staticmethod
    @transaction.atomic
    def record_repayment(*, loan: Loan, amount, source, created_by=None, reference="", note=""):
        """
        Posts a repayment against the loan's ledger stream, then allocates
        it across outstanding installments oldest-first — a payment can
        partially or fully cover one installment and spill into the next.
        Marks the loan COMPLETED once fully repaid.
        """
        if loan.status != Loan.Status.ACTIVE:
            raise LoanError(f"Cannot record a repayment against a loan in status '{loan.status}'.")
        if amount <= 0:
            raise LoanError("amount must be positive.")

        LedgerService.post_loan_entry(
            loan=loan,
            entry_type=LedgerEntry.EntryType.REPAYMENT,
            amount=amount,
            source=source,
            created_by=created_by,
            reference=reference,
            note=note,
        )

        remaining = amount
        installments = loan.repayment_schedule.exclude(status=RepaymentSchedule.Status.PAID).order_by("installment_number")
        for installment in installments:
            if remaining <= 0:
                break
            applied = min(remaining, installment.outstanding)
            installment.paid_amount += applied
            installment.status = (
                RepaymentSchedule.Status.PAID
                if installment.outstanding <= 0
                else RepaymentSchedule.Status.PARTIALLY_PAID
            )
            if installment.status == RepaymentSchedule.Status.PAID:
                installment.paid_at = timezone.now()
            installment.save(update_fields=["paid_amount", "status", "paid_at"])
            remaining -= applied

        if LedgerService.get_loan_outstanding_balance(loan) <= 0:
            loan.status = Loan.Status.COMPLETED
            loan.save(update_fields=["status"])

        return loan
