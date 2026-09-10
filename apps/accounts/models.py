from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.core.fields import EncryptedCharField


class User(AbstractUser):
    """
    Single auth model for everyone who logs in — members and admins alike.
    `role` distinguishes a plain member from the admin tiers described in
    the system design.
    Member-specific KYC data lives on the linked MemberProfile, not here,
    so an admin-only account never carries irrelevant fields.
    """

    class Role(models.TextChoices):
        MEMBER = "member", "Member"
        TREASURER = "treasurer", "Treasurer"
        SECRETARY = "secretary", "Secretary"
        CHAIRMAN = "chairman", "Chairman"
        SUPERADMIN = "superadmin", "Super Admin"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER)
    phone_number = models.CharField(max_length=20, blank=True)

    @property
    def is_admin_tier(self):
        return self.role != self.Role.MEMBER

    def __str__(self):
        return self.get_full_name() or self.username


class MemberProfile(models.Model):
    """
    KYC + membership status for a Member-role user.
    BVN/NIN are stored via EncryptedCharField (Fernet, see apps.core.fields) —
    never logged, never exposed outside what's strictly needed.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending Approval"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        EXITED = "exited", "Exited"
        REJECTED = "rejected", "Registration Rejected"

    class IdType(models.TextChoices):
        BVN = "bvn", "BVN"
        NIN = "nin", "NIN"

    class Gender(models.TextChoices):
        MALE = "MALE", "Male"
        FEMALE = "FEMALE", "Female"

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="member_profile"
    )

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    id_type = models.CharField(max_length=10, choices=IdType.choices)
    id_number = EncryptedCharField(max_length=120)  # BVN or NIN, encrypted at rest
    gender = models.CharField(
        max_length=10, choices=Gender.choices
    )  # required by PayVessel's verification API

    date_of_birth = models.DateField(null=True, blank=True)
    next_of_kin_name = models.CharField(max_length=255, blank=True)
    next_of_kin_phone = models.CharField(max_length=20, blank=True)
    employment_info = models.CharField(max_length=255, blank=True)

    # Filled in once a PayVessel reserved virtual account is created
    payvessel_account_number = models.CharField(max_length=40, blank=True)
    payvessel_bank_name = models.CharField(max_length=100, blank=True)

    joined_at = models.DateTimeField(auto_now_add=True)
    rejection_reason = models.TextField(blank=True)

    class Meta:
        indexes = [models.Index(fields=["status"])]
        permissions = [
            ("can_approve_members", "Can approve pending member registrations"),
        ]

    def __str__(self):
        return f"{self.user} ({self.status})"

    @property
    def membership_duration_days(self):
        from django.utils import timezone

        return (timezone.now() - self.joined_at).days


class KYCVerification(models.Model):
    """
    Result of a single BVN/NIN verification API call. One
    member may have several rows over time (e.g. a retry after a typo
    correction) — this is a log, not a single mutable status field, so the
    history of verification attempts is never lost.
    """

    class MatchStatus(models.TextChoices):
        MATCH = "match", "Match"
        MISMATCH = "mismatch", "Mismatch"
        PENDING = "pending", "Pending / Error"

    member = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="kyc_verifications"
    )
    id_type = models.CharField(max_length=10, choices=MemberProfile.IdType.choices)
    match_status = models.CharField(
        max_length=10, choices=MatchStatus.choices, default=MatchStatus.PENDING
    )
    # Raw match-field response from PayVessel (name_match_rlt, birthday_match_rlt,
    # etc.) — or an error payload if the call failed. Never contains the raw
    # BVN/NIN itself, only PayVessel's verdict on it.
    raw_response = models.JSONField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.member} — {self.id_type} — {self.match_status}"
