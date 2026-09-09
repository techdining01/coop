"""
Celery Beat schedule for this task is configured via Django admin
(django_celery_beat's PeriodicTask UI — the beat service in
docker-compose.yml already runs with DatabaseScheduler), not hardcoded
here, so the cooperative can adjust frequency/amount without a deploy.
"""

from celery import shared_task
from django.contrib.auth import get_user_model
from django.db import transaction

from apps.accounts.models import MemberProfile

from .models import LedgerEntry
from .services import LedgerService

User = get_user_model()



def distribute_profit_sharing(total_pool_amount: str):
    """
    Distributes `total_pool_amount` (a decimal string — Celery serializes
    args as JSON, so Decimal isn't passed directly) across all active
    members' savings, proportional to each member's current confirmed
    savings balance — the Mudarabah-style profit-sharing pattern (profit
    tied to actual balance held, not a fixed rate promised in advance,
    which would function like interest).

    NOTE: this task does not decide the pool amount itself — that's a
    cooperative governance decision (how much profit was actually made
    this period) passed in as an argument when the periodic task is
    configured or triggered. No profit-rate or accrual formula is
    invented here beyond "proportional to balance", since nothing more
    specific was specified.
    """
    from decimal import Decimal

    pool = Decimal(total_pool_amount)
    if pool <= 0:
        return

    active_profiles = MemberProfile.objects.filter(status=MemberProfile.Status.ACTIVE).select_related("user")
    balances = {p.user: LedgerService.get_savings_balance(p.user) for p in active_profiles}
    total_savings = sum(balances.values())

    if total_savings <= 0:
        return  # nothing to distribute against

    with transaction.atomic():
        for member, balance in balances.items():
            if balance <= 0:
                continue
            share = (pool * balance / total_savings).quantize(Decimal("0.01"))
            if share <= 0:
                continue
            LedgerService.post_savings_entry(
                member=member,
                entry_type=LedgerEntry.EntryType.PROFIT_DISTRIBUTION,
                amount=share,
                source=LedgerEntry.Source.SYSTEM,
                created_by=None,
                note="Periodic profit-sharing distribution",
            )


@shared_task
def generate_weekly_ledger_export():
    """
    Runs weekly (schedule configured via django_celery_beat's admin UI,
    same pattern as distribute_profit_sharing). Covers the 7 days ending
    today. Creates the LedgerExport row that the admin download view
    reads from — see ledger/views.py.
    """
    from datetime import timedelta

    from django.utils import timezone

    from .exports import generate_weekly_export_pdf
    from .models import LedgerExport

    period_end = timezone.now().date()
    period_start = period_end - timedelta(days=7)

    file_path = generate_weekly_export_pdf(period_start, period_end)

    LedgerExport.objects.create(
        period_start=period_start,
        period_end=period_end,
        file_path=file_path,
    )


@shared_task
def cleanup_downloaded_export(export_id):
    """
    Queued (with a short countdown — see ledger/views.py) right after an
    admin's first download of a given export, NOT on a blind schedule.
    Only deletes if downloaded_at is actually set — an export nobody has
    downloaded yet is never touched by this task, so a forgotten download
    never turns into lost data.
    """
    import os

    from .models import LedgerExport

    try:
        export = LedgerExport.objects.get(pk=export_id)
    except LedgerExport.DoesNotExist:
        return

    if export.downloaded_at is None or export.deleted_at is not None:
        return  # not downloaded yet, or already cleaned up — nothing to do

    if os.path.exists(export.file_path):
        os.remove(export.file_path)

    from django.utils import timezone

    export.deleted_at = timezone.now()
    export.save(update_fields=["deleted_at"])
