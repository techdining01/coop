from django.conf import settings
from django.db import models


class CooperativeSettings(models.Model):
    """
    Single-row configuration for cooperative-wide values that aren't
    per-loan-tier (those live in LoanEligibilityPolicy).
    Enforced as a singleton via save() below.
    """

    required_share_capital_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass  # singleton — never actually delete this row

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Cooperative Settings"


class LedgerEntry(models.Model):
    """
    The single source of truth for money movement. IMMUTABLE — application
    code must never .save() an update to amount/type/status after creation,
    and must never .delete() a row. Corrections are made by creating a new
    entry with type/status reflecting the reversal (see services.py), never
    by editing history.
      """

    class EntryType(models.TextChoices):
        DEPOSIT = "deposit", "Deposit"
        WITHDRAWAL = "withdrawal", "Withdrawal"
        LOAN_DISBURSEMENT = "loan_disbursement", "Loan Disbursement"
        REPAYMENT = "repayment", "Loan Repayment"
        PROFIT_DISTRIBUTION = "profit_distribution", "Profit-Sharing Distribution"
        PENALTY = "penalty", "Penalty"
        ADJUSTMENT = "adjustment", "Manual Adjustment"
        SHARE_CAPITAL_CONTRIBUTION = "share_capital_contribution", "Share Capital Contribution"

    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmed"
        REVERSED = "reversed", "Reversed"

    class Source(models.TextChoices):
        WEBHOOK = "webhook", "PayVessel Webhook"
        RECEIPT_UPLOAD = "receipt_upload", "Receipt Upload (Manual Review)"
        MANUAL = "manual", "Manual Entry (No Receipt)"
        SYSTEM = "system", "System (e.g. profit distribution, penalty)"

    member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
    )
    # Set only for loan_disbursement/repayment/penalty entries — string
    # reference avoids a circular import (apps.loans imports apps.ledger,
    # not the other way around). Null for every savings-side entry.
    loan = models.ForeignKey(
        "loans.Loan",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
    )
    entry_type = models.CharField(max_length=32, choices=EntryType.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CONFIRMED)
    source = models.CharField(max_length=20, choices=Source.choices)

    amount = models.DecimalField(max_digits=14, decimal_places=2)  # always positive; direction comes from entry_type
    # For a SAVINGS entry: the member's savings balance after this entry.
    # For a LOAN entry: that specific loan's outstanding balance after
    # this entry (starts at total repayable on disbursement, decreases
    # with repayments, increases with penalties). Same column, two
    # different "streams" — always read it together with entry_type/loan,
    # never in isolation across types.
    balance_after = models.DecimalField(max_digits=14, decimal_places=2)

    reference = models.CharField(max_length=100, blank=True, db_index=True)
    note = models.CharField(max_length=255, blank=True)

    # For a reversal entry, points at the entry it reverses. Never null on
    # a REVERSED-status row's counterpart adjustment.
    reverses = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reversed_by"
    )
    reversal_reason = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ledger_entries_created",
        help_text="Null when source=webhook (system-authorized, not a human action).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["member", "created_at"]),
            models.Index(fields=["entry_type"]),
        ]
        permissions = [
            ("can_record_manual_transaction", "Can record manual transactions and loan repayments (Treasurer-level)"),
            ("can_view_ledger_exports", "Can view and download weekly ledger exports"),
        ]

    def __str__(self):
        return f"{self.entry_type} {self.amount} — {self.member} ({self.status})"

    # Entry types whose balance_after is computed against the member's
    # SAVINGS balance.
    SAVINGS_ENTRY_TYPES = {
        EntryType.DEPOSIT,
        EntryType.WITHDRAWAL,
        EntryType.PROFIT_DISTRIBUTION,
        EntryType.SHARE_CAPITAL_CONTRIBUTION,
        EntryType.ADJUSTMENT,
    }
    SAVINGS_CREDIT_TYPES = {
        EntryType.DEPOSIT,
        EntryType.PROFIT_DISTRIBUTION,
        EntryType.SHARE_CAPITAL_CONTRIBUTION,
    }
    SAVINGS_DEBIT_TYPES = {
        EntryType.WITHDRAWAL,
    }
    # ADJUSTMENT can go either way — its direction is passed explicitly by
    # the caller rather than inferred from entry_type (see services.py).

    # Entry types whose balance_after is computed against a specific
    # Loan's OUTSTANDING balance instead. Always paired with a
    # non-null `loan` FK.
    LOAN_ENTRY_TYPES = {
        EntryType.LOAN_DISBURSEMENT,
        EntryType.REPAYMENT,
        EntryType.PENALTY,
    }
    LOAN_CREDIT_TYPES = {
        # "Credit" here means increases what the member owes — disbursing
        # the loan or adding a penalty both make the outstanding balance
        # go UP, same direction math as a savings credit even though the
        # real-world meaning is the opposite of "money in the member's favor".
        EntryType.LOAN_DISBURSEMENT,
        EntryType.PENALTY,
    }
    LOAN_DEBIT_TYPES = {
        EntryType.REPAYMENT,
    }

    @property
    def signed_amount(self):
        """Positive for credits, negative for debits — used when computing balance_after."""
        if self.entry_type in self.SAVINGS_CREDIT_TYPES:
            return self.amount
        if self.entry_type in self.SAVINGS_DEBIT_TYPES:
            return -self.amount
        if self.entry_type in self.LOAN_CREDIT_TYPES:
            return self.amount
        if self.entry_type in self.LOAN_DEBIT_TYPES:
            return -self.amount
        # ADJUSTMENT: sign was already baked into `amount` by the caller.
        return self.amount


class LedgerExport(models.Model):
    """Weekly downloadable PDF snapshot of all transactions ."""

    period_start = models.DateField()
    period_end = models.DateField()
    file_path = models.CharField(max_length=500)
    generated_at = models.DateTimeField(auto_now_add=True)
    downloaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    downloaded_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-generated_at"]

    def __str__(self):
        return f"Ledger export {self.period_start} – {self.period_end}"
