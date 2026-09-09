from celery import shared_task
from django.utils import timezone

from apps.accounts1.models import KYCVerification, MemberProfile

from .client import PayVesselClient, PayVesselError

import logging

logger = logging.getLogger(__name__)


@shared_task
def verify_identity_task(member_profile_id):
    """
    Fired once at registration (Section 5a). Calls PayVessel's BVN/NIN
    Verification API and records the match result — never blocks
    registration, never auto-activates membership on a MATCH (an admin
    still approves; see MemberProfileAdmin.approve_members).
    """
    try:
        profile = MemberProfile.objects.select_related("user").get(pk=member_profile_id)
    except MemberProfile.DoesNotExist:
        return

    user = profile.user
    client = PayVesselClient()

    common_kwargs = dict(
        first_name=user.first_name,
        last_name=user.last_name,
        middle_name="",
        gender=profile.gender,
        birthday=profile.date_of_birth.isoformat() if profile.date_of_birth else "",
        phone_number=user.phone_number,
    )

    try:
        if profile.id_type == MemberProfile.IdType.NIN:
            response = client.verify_nin(nin=profile.id_number, **common_kwargs)
        else:
            response = client.verify_bvn(bvn=profile.id_number, **common_kwargs)
    except PayVesselError as exc:
        KYCVerification.objects.create(
            member=user,
            id_type=profile.id_type,
            match_status=KYCVerification.MatchStatus.PENDING,
            raw_response={"error": str(exc)},
        )
        return

    data = response.get("data") or {}
    # Per the confirmed NIN response shape: per-field verdicts, not raw
    # values to compare ourselves. Both name and birthday must MATCH —
    # gender/phone are recorded but not treated as blocking on their own,
    # since a typo'd phone number shouldn't block a genuine member.
    is_match = bool(
        response.get("success")
        and data.get("name_match_rlt") == "MATCH"
        and data.get("birthday_match_rlt") == "MATCH"
    )

    KYCVerification.objects.create(
        member=user,
        id_type=profile.id_type,
        match_status=KYCVerification.MatchStatus.MATCH if is_match else KYCVerification.MatchStatus.MISMATCH,
        raw_response=data,
        verified_at=timezone.now(),
    )


@shared_task(bind=True, max_retries=5)
def create_reserved_account_task(self, member_profile_id):
    """
    Fired when an admin approves a member ("On admin approval:
    PayVessel reserved (STATIC) virtual account created"). Idempotent —
    no-ops if the member already has an account number.

    Previously this task had several bugs that caused it to ALWAYS fail
    silently (no account number assigned):
    - Silently returned for NIN-only members (PayVessel supports NIN for
      PalmPay STATIC accounts)
    - Sent wrong payload field names (first_name, phone_number, etc.)
      instead of PayVessel's expected name, phoneNumber, bankcode, businessid
    - Omitted the required bankcode and businessid fields entirely
    - Parsed the response looking for response["data"]["account_number"],
      but PayVessel returns banks[0].accountNumber (nested array, camelCase)
    - Silently swallowed all PayVesselError exceptions — no logging, no retry,
      no admin notification

    Fixes: correct payload, correct response parsing, NIN support, retry
    with exponential backoff, error tracking on MemberProfile.
    """
    try:
        profile = MemberProfile.objects.select_related("user").get(pk=member_profile_id)
    except MemberProfile.DoesNotExist:
        return

    if profile.payvessel_account_number:
        return  # already has one

    user = profile.user
    client = PayVesselClient()

    id_kwargs = {}
    if profile.id_type == MemberProfile.IdType.BVN:
        id_kwargs["bvn"] = profile.id_number
    else:
        id_kwargs["nin"] = profile.id_number

    try:
        response = client.create_reserved_account(
            member=user,
            first_name=user.first_name,
            last_name=user.last_name,
            phone_number=user.phone_number,
            email=user.email,
            **id_kwargs,
        )
    except PayVesselError as exc:
        error_msg = str(exc)
        logger.error(
            "create_reserved_account_task: PayVessel API error for member %s "
            "(profile pk=%s): %s",
            user.username, profile.pk, error_msg,
            exc_info=True,
        )
        profile.payvessel_error = error_msg
        profile.payvessel_error_count = profile.payvessel_error_count + 1
        profile.save(update_fields=["payvessel_error", "payvessel_error_count"])

        raise self.retry(
            args=[member_profile_id],
            exc=exc,
            countdown=min(60 * 2 ** self.request.retries, 3600),
            max_retries=5,
        )

    # PayVessel response format:
    #   { "status": true, "banks": [{ "bankName": "...", "accountNumber": "..." }] }
    banks = response.get("banks") or []
    if not banks:
        error_msg = f"PayVessel response had no banks array: {response}"
        logger.error("create_reserved_account_task: %s (profile pk=%s)", error_msg, profile.pk)
        profile.payvessel_error = error_msg
        profile.payvessel_error_count = profile.payvessel_error_count + 1
        profile.save(update_fields=["payvessel_error", "payvessel_error_count"])
        raise self.retry(
            args=[member_profile_id],
            countdown=min(60 * 2 ** self.request.retries, 3600),
            max_retries=5,
        )

    # Prefer 9Payment Service Bank (works for everyone), fall back to first.
    chosen = next((b for b in banks if b.get("bankName") == "9Payment Service Bank"), banks[0])
    account_number = chosen.get("accountNumber", "")
    bank_name = chosen.get("bankName", "")

    if not account_number:
        error_msg = f"PayVessel returned banks but no accountNumber: {response}"
        logger.error("create_reserved_account_task: %s (profile pk=%s)", error_msg, profile.pk)
        profile.payvessel_error = error_msg
        profile.payvessel_error_count = profile.payvessel_error_count + 1
        profile.save(update_fields=["payvessel_error", "payvessel_error_count"])
        raise self.retry(
            args=[member_profile_id],
            countdown=min(60 * 2 ** self.request.retries, 3600),
            max_retries=5,
        )

    profile.payvessel_account_number = account_number
    profile.payvessel_bank_name = bank_name
    profile.payvessel_error = ""
    profile.payvessel_error_count = 0
    profile.save(update_fields=["payvessel_account_number", "payvessel_bank_name", "payvessel_error", "payvessel_error_count"])

    logger.info(
        "create_reserved_account_task: account created for member %s "
        "(profile pk=%s): %s @ %s",
        user.username, profile.pk, account_number, bank_name,
    )
