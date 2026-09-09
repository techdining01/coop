from django.conf import settings
from django.db import models

from apps.ledger.models import LedgerEntry


def receipt_upload_path(instance, filename):
    return f"receipts/{instance.member_id}/{filename}"


class WebhookEvent(models.Model):
    """
    One row per PayVessel webhook delivery. The unique constraint on
    transaction_reference is the real duplicate-prevention mechanism
     — WebhookService checks it, but the DB constraint is what
    actually prevents a double-post if two webhook retries arrive at
    almost the same instant.
    """

    class Status(models.TextChoices):
        PROCESSED = "processed", "Processed"
        REJECTED_SIGNATURE = "rejected_signature", "Rejected — Invalid Signature"
        REJECTED_IP = "rejected_ip", "Rejected — IP Not Allowlisted"
        REJECTED_UNMATCHED = "rejected_unmatched", "Rejected — No Member Found for Account"
        DUPLICATE = "duplicate", "Duplicate — Already Processed"

    provider = models.CharField(max_length=20, default="payvessel")
    transaction_reference = models.CharField(max_length=150, unique=True, db_index=True)
    raw_payload = models.JSONField()
    status = models.CharField(max_length=30, choices=Status.choices)
    resulting_ledger_entry = models.ForeignKey(
        LedgerEntry, null=True, blank=True, on_delete=models.SET_NULL
    )
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_at"]

    def __str__(self):
        return f"{self.provider} {self.transaction_reference} ({self.status})"


class PaymentProof(models.Model):
    """
    Uploaded receipt — Section 5c. Deliberately NO extracted fields, NO
    confidence score, NO OCR/LLM anywhere on this model. `claimed_type`
    and `claimed_amount` are what the member typed in; an admin reads the
    file themselves and enters the real values on approval.
    """

    class EntryChoice(models.TextChoices):
        DEPOSIT = "deposit", "Savings Deposit"
        SHARE_CAPITAL = "share_capital_contribution", "Share Capital Contribution"
        # loan_repayment intentionally omitted — no Loan model until Phase 3

    class Status(models.TextChoices):
        PENDING_REVIEW = "pending_review", "Pending Review"
        POSSIBLE_DUPLICATE = "possible_duplicate", "Possible Duplicate"
        CONFIRMED = "confirmed", "Confirmed"
        REJECTED = "rejected", "Rejected"

    member = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payment_proofs"
    )
    file = models.FileField(upload_to=receipt_upload_path)
    file_hash = models.CharField(max_length=120, db_index=True)  # sha256 hex — duplicate detection, no OCR involved

    claimed_type = models.CharField(max_length=64, choices=EntryChoice.choices)
    claimed_amount = models.DecimalField(max_digits=14, decimal_places=2)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_REVIEW)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    resulting_ledger_entry = models.ForeignKey(
        LedgerEntry, null=True, blank=True, on_delete=models.SET_NULL
    )

    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]
        indexes = [models.Index(fields=["status"])]

    def __str__(self):
        return f"Receipt from {self.member} — {self.status}"


def reconciliation_upload_path(instance, filename):
    return f"reconciliation/{instance.uploaded_by_id}/{filename}"


class ReconciliationRun(models.Model):
    """
    One row per reconciliation pass (— "regular reconciliation
    between PayVessel settlement records and the app-recorded ledger").

    IMPLEMENTATION NOTE: PayVessel's docs (as fetched for this build) don't
    expose a confirmed settlement/statement-export API endpoint the way
    they do for reserved accounts and BVN/NIN verification — so rather
    than guess at one, this tool works from a CSV an admin exports from
    the PayVessel merchant dashboard and uploads here. If PayVessel later
    confirms a settlement API, this becomes the natural place to fetch it
    automatically instead of requiring the manual upload step.
    """

    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    source_file = models.FileField(upload_to=reconciliation_upload_path)

    total_rows_in_file = models.PositiveIntegerField(default=0)
    matched_count = models.PositiveIntegerField(default=0)
    discrepancy_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Reconciliation run #{self.pk} — {self.created_at:%d %b %Y} ({self.discrepancy_count} discrepancies)"


class ReconciliationDiscrepancy(models.Model):
    class Kind(models.TextChoices):
        AMOUNT_MISMATCH = "amount_mismatch", "Amount Mismatch"
        MISSING_LOCALLY = "missing_locally", "In PayVessel File, Not Found Locally"
        MISSING_IN_FILE = "missing_in_file", "Processed Locally, Not Found in PayVessel File"

    run = models.ForeignKey(ReconciliationRun, on_delete=models.CASCADE, related_name="discrepancies")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    transaction_reference = models.CharField(max_length=150, blank=True)
    expected_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    actual_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    webhook_event = models.ForeignKey(WebhookEvent, null=True, blank=True, on_delete=models.SET_NULL)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["kind", "transaction_reference"]

    def __str__(self):
        return f"{self.get_kind_display()} — {self.transaction_reference}"
