from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import models


class LoanEligibilityPolicy(models.Model):
    """
    A named eligibility tier (Section 6) — e.g. "Starter Loan" at 3 months
    tenure + a lower cap, "Standard Loan" at 6 months + a higher cap.
    Admin-editable rows, not hardcoded values, so the committee can add or
    adjust tiers without a code change. The Shared Capital gate is NOT a
    per-tier field — it's a single cooperative-wide prerequisite checked
    before any tier (see CooperativeSettings.required_share_capital_amount
    in apps.ledger, and eligibility.py's check order).
    """

    name = models.CharField(max_length=100, unique=True)
    min_tenure_months = models.PositiveIntegerField()
    min_savings_balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    max_loan_multiple = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        help_text="Loan amount is capped at this many times the member's current savings balance.",
    )
    is_active = models.BooleanField(default=True, help_text="Inactive tiers are hidden from new applications but existing loans keep referencing them.")

    class Meta:
        ordering = ["min_tenure_months"]
        verbose_name_plural = "Loan eligibility policies"

    def __str__(self):
        return f"{self.name} ({self.min_tenure_months}mo, ₦{self.min_savings_balance}+, {self.max_loan_multiple}x cap)"


class Loan(models.Model):
    """
    Single model covering the whole lifecycle — application through
    completion — per the system design's compact "LoanApplication → Loan"
    notation: the application record IS the loan record, its `status`
    field tracks where it is in the pipeline. No separate LoanApplication
    table.

    # financing_structure is fixed at application time (principle
    # on Shariah compliance — no interest, ever):
    #   - QARD_HASAN: interest-free. total_repayable == principal.
    #   - MURABAHA: a fixed profit margin agreed upfront (not compounding,
    #     not tied to time elapsed) — total_repayable == principal + murabaha_profit_amount.
    """

    

    class Status(models.TextChoices):
        PENDING = "pending", "Pending Review"
        GUARANTOR_PENDING = "guarantor_pending", "Awaiting Guarantor"
        APPROVED = "approved", "Approved — Awaiting Disbursement"
        REJECTED = "rejected", "Rejected"
        DISBURSED = "disbursed", "Disbursed"  # transient — becomes ACTIVE once the schedule is generated
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        DEFAULTED = "defaulted", "Defaulted"

    member = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="loans")
    # Which tier the member applied under — determines which tenure/savings/
    # cap rules were checked at application time. PROTECT: a
    # tier that's been applied against shouldn't be deletable out from
    # under an existing loan; deactivate it instead (is_active=False).
    policy = models.ForeignKey(LoanEligibilityPolicy, on_delete=models.PROTECT, related_name="loans")
    principal = models.DecimalField(max_digits=14, decimal_places=2)
    # financing_structure = models.CharField(max_length=20, choices=FinancingStructure.choices)
    # Only set (and only meaningful) for MURABAHA — a flat, agreed-upfront
    # amount, never a rate applied over time. Zero/blank for QARD_HASAN.
    # murabaha_profit_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    tenure_months = models.PositiveIntegerField()
    purpose = models.CharField(max_length=255)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    # Simplification, flagged rather than hidden: at most ONE guarantor per
    # loan for now. A cooperative requiring multiple guarantors per loan
    # would need a separate GuarantorRequest-per-loan model — reasonable
    # follow-up, not built here without being asked for.
    guarantor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="guaranteed_loans",
    )
    guarantor_accepted_at = models.DateTimeField(null=True, blank=True)
    guarantor_declined_at = models.DateTimeField(null=True, blank=True)

    applied_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    disbursed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-applied_at"]
        indexes = [models.Index(fields=["status"])]
        permissions = [
            ("can_review_loans", "Can approve, reject, and disburse loan applications (Chairman-level)"),
        ]

    def __str__(self):
        return f"{self.member} — ₦{self.principal} ({self.status})"

    @property
    def total_repayable(self) -> Decimal:
        # if self.financing_structure == self.FinancingStructure.QARD_HASAN:
        #     return self.principal
        return self.principal #+ self.murabaha_profit_amount

    def generate_repayment_schedule(self):
        """
        Splits total_repayable evenly across tenure_months, monthly,
        starting one month after disbursement. Any rounding remainder
        (DecimalField division rarely divides evenly) is absorbed into the
        LAST installment so the schedule always sums exactly to
        total_repayable — never silently over- or under-collects.
        """
        from dateutil.relativedelta import relativedelta
        from django.utils import timezone

        if self.repayment_schedule.exists():
            raise ValueError("Repayment schedule already generated for this loan.")

        total = self.total_repayable
        n = self.tenure_months
        base_installment = (total / n).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        running_total = Decimal("0.00")
        start_date = timezone.now().date()

        rows = []
        for i in range(1, n + 1):
            if i < n:
                amount = base_installment
            else:
                amount = total - running_total  # last installment absorbs rounding remainder
            running_total += amount
            rows.append(
                RepaymentSchedule(
                    loan=self,
                    installment_number=i,
                    due_date=start_date + relativedelta(months=i),
                    expected_amount=amount,
                )
            )
        RepaymentSchedule.objects.bulk_create(rows)


class RepaymentSchedule(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PARTIALLY_PAID = "partially_paid", "Partially Paid"
        PAID = "paid", "Paid"
        OVERDUE = "overdue", "Overdue"

    loan = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name="repayment_schedule")
    installment_number = models.PositiveIntegerField()
    due_date = models.DateField()
    expected_amount = models.DecimalField(max_digits=14, decimal_places=2)
    paid_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["loan", "installment_number"]
        unique_together = ["loan", "installment_number"]
        indexes = [models.Index(fields=["status", "due_date"])]

    def __str__(self):
        return f"{self.loan} — installment {self.installment_number} ({self.status})"

    @property
    def outstanding(self):
        """How much of this specific installment is still unpaid."""
        return self.expected_amount - self.paid_amount
