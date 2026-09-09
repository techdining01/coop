from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """
    Every admin/financial action, traceable to a human decision and a
    timestamp. Deliberately simple (no
    GenericForeignKey) for Phase 1 — a string model name + id is enough to
    trace "who did what to which record", and avoids the extra complexity
    of contenttypes for what is, in practice, always looked up by a human
    reading a log, not queried programmatically across types.
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=100)  # e.g. "ledger_entry.created", "member.suspended"
    target_model = models.CharField(max_length=100)  # e.g. "LedgerEntry", "MemberProfile"
    target_id = models.CharField(max_length=64)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    reason = models.TextField(blank=True)  # mandatory for reversals/adjustments, enforced in the service layer
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["target_model", "target_id"]),
            models.Index(fields=["actor", "created_at"]),
        ]
        permissions = [
            ("can_view_reports", "Can view and download bulk reports (member statements, loan book, overdue list)"),
        ]

    def __str__(self):
        return f"{self.actor} {self.action} {self.target_model}#{self.target_id}"


class Notification(models.Model):
    class Channel(models.TextChoices):
        PUSH = "push", "Push"
        EMAIL = "email", "Email"
        SMS = "sms", "SMS"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    channel = models.CharField(max_length=10, choices=Channel.choices)
    subject = models.CharField(max_length=255, blank=True)
    content = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.channel} to {self.recipient} — {self.status}"
