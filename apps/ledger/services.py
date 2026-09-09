"""
LedgerService is the ONLY sanctioned way to create or reverse a LedgerEntry.
No view, task, or admin action should call LedgerEntry.objects.create()
directly — that bypasses balance computation, audit logging, and the
locking that prevents a race condition from producing two entries with
the same (wrong) balance_after.

Design principles this enforces:
  1. Ledger-first — balance is always derived from confirmed entries, never
     mutated directly.
  5. Every admin action is audited — every post/reversal writes an AuditLog row.

STREAM DISCRIMINATION: a member has one savings "stream" (loan IS NULL)
and each of their loans has its own stream (loan=<that Loan>). Every
balance/previous-balance lookup filters by loan being null or set — NOT
by entry_type — because a reversal is always typed ADJUSTMENT regardless
of which stream it corrects, and typed-filtering would silently drop
reversals from a loan's balance calculation. If you add a new entry_type
in the future, you don't need to touch the balance queries at all: just
make sure `loan` is set correctly when posting it.
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from apps.core.models import AuditLog
from apps.ledger.models import CooperativeSettings, LedgerEntry


class LedgerError(Exception):
    pass


class LedgerService:
    @staticmethod
    @transaction.atomic
    def post_savings_entry(*, member, entry_type, amount, source, created_by=None, reference="", note=""):
        """
        Post a savings-side entry (deposit, withdrawal, profit_distribution,
        share_capital_contribution). `amount` must always be positive;
        direction is derived from entry_type via LedgerEntry.signed_amount.
        """
        if entry_type not in LedgerEntry.SAVINGS_ENTRY_TYPES:
            raise LedgerError(
                f"'{entry_type}' is not a savings-side entry type. Use post_loan_entry() for loan entries."
            )
        if entry_type == LedgerEntry.EntryType.ADJUSTMENT:
            raise LedgerError("Use LedgerService.post_adjustment() for adjustments — a reason is mandatory.")
        if amount <= 0:
            raise LedgerError("amount must be positive.")

        previous = LedgerService._lock_latest(member=member, loan=None)
        previous_balance = previous.balance_after if previous else Decimal("0.00")

        entry = LedgerEntry(
            member=member,
            loan=None,
            entry_type=entry_type,
            status=LedgerEntry.Status.CONFIRMED,
            source=source,
            amount=amount,
            reference=reference,
            note=note,
            created_by=created_by,
        )
        entry.balance_after = previous_balance + entry.signed_amount
        entry.save()

        AuditLog.objects.create(
            actor=created_by,
            action="ledger_entry.created",
            target_model="LedgerEntry",
            target_id=str(entry.pk),
            after={
                "entry_type": entry_type,
                "amount": str(amount),
                "balance_after": str(entry.balance_after),
                "source": source,
                "member_id": member.pk,
            },
        )
        return entry

    @staticmethod
    @transaction.atomic
    def post_loan_entry(*, loan, entry_type, amount, source, created_by=None, reference="", note=""):
        """
        Post a loan-side entry (loan_disbursement, repayment, penalty).
        balance_after here is that LOAN's outstanding balance, not the
        member's savings balance — see the note on LedgerEntry.balance_after.
        `member` is set to loan.member automatically.
        """
        if entry_type not in LedgerEntry.LOAN_ENTRY_TYPES:
            raise LedgerError(
                f"'{entry_type}' is not a loan-side entry type. Use post_savings_entry() instead."
            )
        if amount <= 0:
            raise LedgerError("amount must be positive.")

        previous = LedgerService._lock_latest(member=loan.member, loan=loan)
        previous_balance = previous.balance_after if previous else Decimal("0.00")

        entry = LedgerEntry(
            member=loan.member,
            loan=loan,
            entry_type=entry_type,
            status=LedgerEntry.Status.CONFIRMED,
            source=source,
            amount=amount,
            reference=reference,
            note=note,
            created_by=created_by,
        )
        entry.balance_after = previous_balance + entry.signed_amount
        entry.save()

        AuditLog.objects.create(
            actor=created_by,
            action="ledger_entry.loan_entry_created",
            target_model="LedgerEntry",
            target_id=str(entry.pk),
            after={
                "entry_type": entry_type,
                "amount": str(amount),
                "balance_after": str(entry.balance_after),
                "loan_id": loan.pk,
                "source": source,
            },
        )
        return entry

    @staticmethod
    @transaction.atomic
    def post_adjustment(*, member, signed_amount, created_by, reason, source=LedgerEntry.Source.MANUAL, reference="", loan=None):
        """
        Manual correction — always requires a reason, always audited.
        `signed_amount` may be positive (credit) or negative (debit); the
        stored `amount` is its absolute value, with `entry_type` fixed to
        ADJUSTMENT. Pass `loan` to adjust a specific loan's balance instead
        of the member's savings balance.
        """
        if not reason or not reason.strip():
            raise LedgerError("A reason is mandatory for manual adjustments.")
        if signed_amount == 0:
            raise LedgerError("signed_amount must be non-zero.")

        previous = LedgerService._lock_latest(member=member, loan=loan)
        previous_balance = previous.balance_after if previous else Decimal("0.00")

        entry = LedgerEntry.objects.create(
            member=member,
            loan=loan,
            entry_type=LedgerEntry.EntryType.ADJUSTMENT,
            status=LedgerEntry.Status.CONFIRMED,
            source=source,
            amount=abs(signed_amount),
            balance_after=previous_balance + signed_amount,
            reference=reference,
            created_by=created_by,
        )

        AuditLog.objects.create(
            actor=created_by,
            action="ledger_entry.adjustment_created",
            target_model="LedgerEntry",
            target_id=str(entry.pk),
            after={"signed_amount": str(signed_amount), "balance_after": str(entry.balance_after), "loan_id": loan.pk if loan else None},
            reason=reason,
        )
        return entry

    @staticmethod
    @transaction.atomic
    def reverse_entry(*, entry: LedgerEntry, created_by, reason):
        """
        Never edits or deletes the original entry. Creates a new ADJUSTMENT
        entry with the opposite sign IN THE SAME STREAM (same loan, or
        None for savings) as the original, marks the original as REVERSED,
        and logs why.
        """
        if not reason or not reason.strip():
            raise LedgerError("A reason is mandatory to reverse a ledger entry.")
        if entry.status == LedgerEntry.Status.REVERSED:
            raise LedgerError("This entry has already been reversed.")

        previous = LedgerService._lock_latest(member=entry.member, loan=entry.loan)
        previous_balance = previous.balance_after if previous else Decimal("0.00")
        reversal_signed_amount = -entry.signed_amount

        reversal = LedgerEntry.objects.create(
            member=entry.member,
            loan=entry.loan,
            entry_type=LedgerEntry.EntryType.ADJUSTMENT,
            status=LedgerEntry.Status.CONFIRMED,
            source=LedgerEntry.Source.MANUAL,
            amount=abs(reversal_signed_amount),
            balance_after=previous_balance + reversal_signed_amount,
            reverses=entry,
            reversal_reason=reason,
            created_by=created_by,
        )

        entry.status = LedgerEntry.Status.REVERSED
        entry.save(update_fields=["status"])

        AuditLog.objects.create(
            actor=created_by,
            action="ledger_entry.reversed",
            target_model="LedgerEntry",
            target_id=str(entry.pk),
            before={"status": "confirmed"},
            after={"status": "reversed", "reversal_entry_id": reversal.pk},
            reason=reason,
        )
        return reversal

    @staticmethod
    def _lock_latest(*, member, loan):
        """
        Shared helper: locks and returns the most recent CONFIRMED entry in
        a given stream (a member's savings stream if loan is None, or a
        specific loan's stream otherwise). Used by every post_*/reverse_
        method above so previous-balance reads are always consistent and
        race-safe, and so the stream-discrimination rule lives in exactly
        one place.
        """
        return (
            LedgerEntry.objects.select_for_update()
            .filter(member=member, loan=loan, status=LedgerEntry.Status.CONFIRMED)
            .order_by("-created_at")
            .first()
        )

    @staticmethod
    def get_savings_balance(member) -> Decimal:
        """
        Current savings balance = balance_after of the member's most recent
        CONFIRMED savings-stream entry (loan IS NULL). Cheap read; the
        periodic reconciliation job recomputes from scratch
        and flags drift if this ever disagrees with a full replay.
        """
        latest = (
            LedgerEntry.objects.filter(member=member, loan__isnull=True, status=LedgerEntry.Status.CONFIRMED)
            .order_by("-created_at")
            .first()
        )
        return latest.balance_after if latest else Decimal("0.00")

    @staticmethod
    def get_loan_outstanding_balance(loan) -> Decimal:
        """
        0 before disbursement (no entries yet). After disbursement, this is
        what the member still owes on this specific loan — decreases with
        each repayment, increases with a penalty, and reflects any
        reversal made against this loan's stream.
        """
        latest = (
            LedgerEntry.objects.filter(loan=loan, status=LedgerEntry.Status.CONFIRMED)
            .order_by("-created_at")
            .first()
        )
        return latest.balance_after if latest else Decimal("0.00")

    @staticmethod
    def has_paid_share_capital(member) -> bool:
        """Prerequisite gate — simple yes/no, not a sliding scale."""
        required = CooperativeSettings.load().required_share_capital_amount
        if required <= 0:
            return True
        total = LedgerEntry.objects.filter(
            member=member,
            status=LedgerEntry.Status.CONFIRMED,
            entry_type=LedgerEntry.EntryType.SHARE_CAPITAL_CONTRIBUTION,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        return total >= required
