from celery import shared_task
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.core.models import Notification

from .models import RepaymentSchedule

User = get_user_model()


@shared_task
def remind_upcoming_repayments(days_ahead: int = 3):
    """
    Companion to scan_overdue_repayments — reminds a member BEFORE an
    installment becomes overdue ( "repayment due soon"
    notification). Does not touch `status`; a reminder isn't a status
    change, only overdue actually is.
    """
    today = timezone.now().date()
    target_date = today + timezone.timedelta(days=days_ahead)

    upcoming = RepaymentSchedule.objects.filter(
        due_date=target_date,
        status__in=[RepaymentSchedule.Status.PENDING, RepaymentSchedule.Status.PARTIALLY_PAID],
    ).select_related("loan", "loan__member")

    for installment in upcoming:
        Notification.objects.create(
            recipient=installment.loan.member,
            channel=Notification.Channel.PUSH,
            subject="Loan repayment due soon",
            content=(
                f"Installment #{installment.installment_number} of ₦{installment.outstanding} "
                f"is due on {installment.due_date}."
            ),
        )


@shared_task
def scan_overdue_repayments():
    """
    Daily job . Marks any pending/partially-paid installment
    past its due_date as OVERDUE, then creates Notification records — a
    reminder to the member and an alert to every admin-tier user. Sending
    is handled by whatever dispatches Notification rows (SMS/email/push
    integration — Phase 2's provider choices, not built out here); this
    task's job is just to create the right records at the right time.
    """
    today = timezone.now().date()
    overdue_qs = RepaymentSchedule.objects.filter(
        due_date__lt=today,
        status__in=[RepaymentSchedule.Status.PENDING, RepaymentSchedule.Status.PARTIALLY_PAID],
    ).select_related("loan", "loan__member")

    admin_users = list(User.objects.exclude(role=User.Role.MEMBER))

    for installment in overdue_qs:
        installment.status = RepaymentSchedule.Status.OVERDUE
        installment.save(update_fields=["status"])

        member = installment.loan.member
        Notification.objects.create(
            recipient=member,
            channel=Notification.Channel.PUSH,
            subject="Loan repayment overdue",
            content=(
                f"Installment #{installment.installment_number} of ₦{installment.outstanding} "
                f"was due {installment.due_date} and is now overdue."
            ),
        )
        for admin in admin_users:
            Notification.objects.create(
                recipient=admin,
                channel=Notification.Channel.PUSH,
                subject="Member loan overdue",
                content=(
                    f"{member} — installment #{installment.installment_number} of "
                    f"₦{installment.outstanding} was due {installment.due_date}."
                ),
            )
