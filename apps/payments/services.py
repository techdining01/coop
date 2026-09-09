"""
PayVessel webhook handling. Confirmed against docs.payvessel.com/
api-reference/webhook/verifying-webhooks:

  - Signed with HMAC-SHA512 using the merchant's API secret.
  - Signature arrives in the HTTP_PAYVESSEL_HTTP_SIGNATURE header
    (i.e. the "Payvessel-Http-Signature" header, as Django's WSGI layer
    exposes it).
  - MUST hash the raw request body, not parsed/re-serialized JSON —
    PayVessel's own docs warn that parsing first breaks the signature
    check, since re-serialization can reorder keys or change whitespace.
  - Fixed IP allowlist: 3.255.23.38, 162.246.254.36.
"""

import hashlib
import hmac
import json

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import MemberProfile
from apps.ledger.models import LedgerEntry
from apps.ledger.services import LedgerService

from .models import WebhookEvent

PAYVESSEL_IP_ALLOWLIST = {"3.255.23.38", "162.246.254.36"}


def verify_signature(raw_body: bytes, signature_header: str) -> bool:
    if not signature_header:
        return False
    computed = hmac.new(settings.PAYVESSEL_API_SECRET.encode(), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(computed, signature_header)


def verify_ip(remote_ip: str) -> bool:
    return remote_ip in PAYVESSEL_IP_ALLOWLIST


def get_client_ip(request) -> str:
    """
    Reads the real client IP from X-Forwarded-For, which nginx.conf sets
    via `proxy_set_header X-Forwarded-For`. If this app is ever deployed
    without nginx in front, use request.META["REMOTE_ADDR"] instead —
    trusting X-Forwarded-For without a proxy in front of you is itself a
    spoofing risk, so don't copy this helper into a different deployment
    without checking that assumption still holds.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


class WebhookService:
    @staticmethod
    @transaction.atomic
    def process_payvessel_webhook(*, raw_body: bytes, signature_header: str, remote_ip: str):
        """
        Returns (http_status, message). A signature/IP failure is a
        definite reject (4xx) — not something PayVessel should retry. An
        unexpected internal error is allowed to propagate as an exception,
        which the view lets bubble up to a 5xx response, so PayVessel's
        automatic retry logic kicks in rather than silently losing the
        event.
        """
        if not verify_ip(remote_ip):
            return 403, "IP not allowlisted"

        if not verify_signature(raw_body, signature_header):
            return 401, "Invalid signature"

        try:
            payload = json.loads(raw_body)
        except ValueError:
            return 400, "Invalid JSON"

        reference = payload.get("transaction_reference") or payload.get("reference")
        account_number = payload.get("account_number")
        amount = payload.get("amount")

        if not reference or not account_number or amount is None:
            return 400, "Missing required fields"

        # The unique constraint on transaction_reference is the real guard
        # against a race between two near-simultaneous retries; this
        # pre-check just short-circuits the common case cheaply.
        if WebhookEvent.objects.filter(transaction_reference=reference).exists():
            # 200, not an error status — PayVessel should stop retrying,
            # since as far as it's concerned the delivery succeeded.
            return 200, "Already processed"

        try:
            profile = MemberProfile.objects.select_related("user").get(
                payvessel_account_number=account_number
            )
        except MemberProfile.DoesNotExist:
            WebhookEvent.objects.create(
                provider="payvessel",
                transaction_reference=reference,
                raw_payload=payload,
                status=WebhookEvent.Status.REJECTED_UNMATCHED,
            )
            # Still 200 — this isn't a delivery failure PayVessel should
            # retry, it's a data problem on our side to investigate.
            return 200, "No member found for this account — logged for manual follow-up"

        # Deliberately not wrapped in try/except: a failure here should
        # propagate, roll back this transaction (so no WebhookEvent row is
        # left claiming success), and surface as a 5xx to the view so
        # PayVessel retries the delivery later.
        #
        # KNOWN PHASE 2 SIMPLIFICATION: every webhook-confirmed transfer
        # posts as a plain DEPOSIT. There's no reliable signal in the
        # webhook payload for "this transfer was meant as my Share Capital
        # contribution" vs. an ordinary savings deposit — that intent only
        # exists in the member's head. If a member intends a Share Capital
        # payment via bank transfer, an admin currently has to reverse the
        # auto-posted DEPOSIT and re-post it as SHARE_CAPITAL_CONTRIBUTION
        # via the manual adjustment tool. A cleaner fix (e.g.
        # a "what is this payment for" selector the member sets just
        # before transferring) is a reasonable Phase 2 follow-up, not
        # something this build assumes without being asked for.
        entry = LedgerService.post_savings_entry(
            member=profile.user,
            entry_type=LedgerEntry.EntryType.DEPOSIT,
            amount=amount,
            source=LedgerEntry.Source.WEBHOOK,
            created_by=None,
            reference=reference,
            note="PayVessel webhook — auto-confirmed",
        )

        WebhookEvent.objects.create(
            provider="payvessel",
            transaction_reference=reference,
            raw_payload=payload,
            status=WebhookEvent.Status.PROCESSED,
            resulting_ledger_entry=entry,
            processed_at=timezone.now(),
        )
        return 200, "Processed"
