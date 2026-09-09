from django.conf import settings
from django.contrib.auth.decorators import login_required, permission_required, user_passes_test
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import redirect, render

from apps.ledger.models import LedgerEntry
from apps.ledger.services import LedgerService

from .models import AuditLog


def service_worker_view(request):
    """
    Served at /service-worker.js (root scope), not /static/service-worker.js —
    a service worker can only control paths at or below the URL it's served
    from, so root scope is required for it to manage the whole app.
    """
    path = settings.BASE_DIR / "static" / "service-worker.js"
    with open(path, "rb") as f:
        return HttpResponse(f.read(), content_type="application/javascript")


def landing_view(request):
    """
    Public homepage at /. Authenticated users get routed to their dashboard
    (member → dashboard, admin → admin overview). Anonymous visitors get the
    marketing landing with Login/Register CTAs.
    """
    if request.user.is_authenticated:
        return dashboard_view(request)
    return render(request, "core/landing.html")


@login_required
def dashboard_view(request):
    """Routes to the member savings dashboard or the admin overview, by role."""
    if request.user.is_admin_tier:
        return admin_dashboard(request)
    return member_dashboard(request)


def member_dashboard(request):
    profile = getattr(request.user, "member_profile", None)
    if profile is None or profile.status != profile.Status.ACTIVE:
        return redirect("accounts:pending_approval")

    balance = LedgerService.get_savings_balance(request.user)
    history = (
        LedgerEntry.objects.filter(
            member=request.user,
            status=LedgerEntry.Status.CONFIRMED,
            entry_type__in=LedgerEntry.SAVINGS_ENTRY_TYPES,
        )
        .order_by("-created_at")[:20]
    )
    has_share_capital = LedgerService.has_paid_share_capital(request.user)

    return render(
        request,
        "core/member_dashboard.html",
        {
            "balance": balance,
            "history": history,
            "has_share_capital": has_share_capital,
            "profile": profile,
        },
    )


def admin_dashboard(request):
    # One query per active member — fine for a cooperative-society scale
    # (tens to low hundreds of members). Revisit with a single aggregate
    # query (latest balance_after per member via a window function) if
    # membership grows large enough for this to show up in Sentry as slow.
    total_savings = sum(
        (LedgerService.get_savings_balance(u) for u in _active_members()),
        start=0,
    )
    recent_entries = LedgerEntry.objects.select_related("member").order_by("-created_at")[:20]

    analytics = _dashboard_analytics()

    return render(
        request,
        "core/admin_dashboard.html",
        {
            "total_savings": total_savings,
            "recent_entries": recent_entries,
            **analytics,
        },
    )


def _dashboard_analytics():
    """
    Powers the admin dashboard's chart. "Inflow" = money coming INTO the
    cooperative (deposits, share capital, loan repayments). "Outflow" =
    money going OUT (loan disbursements, withdrawals). Profit-sharing
    distributions and manual adjustments are deliberately excluded from
    both — they're internal reallocations, not money crossing the
    cooperative's boundary, so counting them as inflow/outflow would
    overstate real cash movement.
    """
    from datetime import timedelta

    from django.db.models import Sum
    from django.utils import timezone

    from apps.accounts1.models import MemberProfile

    INFLOW_TYPES = [
        LedgerEntry.EntryType.DEPOSIT,
        LedgerEntry.EntryType.SHARE_CAPITAL_CONTRIBUTION,
        LedgerEntry.EntryType.REPAYMENT,
    ]
    OUTFLOW_TYPES = [
        LedgerEntry.EntryType.LOAN_DISBURSEMENT,
        LedgerEntry.EntryType.WITHDRAWAL,
    ]

    confirmed = LedgerEntry.objects.filter(status=LedgerEntry.Status.CONFIRMED)

    total_inflow = confirmed.filter(entry_type__in=INFLOW_TYPES).aggregate(total=Sum("amount"))["total"] or 0
    total_outflow = confirmed.filter(entry_type__in=OUTFLOW_TYPES).aggregate(total=Sum("amount"))["total"] or 0

    # Last 8 weeks, oldest first — small enough to compute with 8 pairs of
    # queries rather than a fancier single group-by; simple to read, and
    # fine at cooperative-society transaction volume.
    today = timezone.now().date()
    weekly_labels = []
    weekly_inflow = []
    weekly_outflow = []
    for i in range(7, -1, -1):
        week_end = today - timedelta(days=7 * i)
        week_start = week_end - timedelta(days=6)
        week_qs = confirmed.filter(created_at__date__gte=week_start, created_at__date__lte=week_end)
        inflow = week_qs.filter(entry_type__in=INFLOW_TYPES).aggregate(total=Sum("amount"))["total"] or 0
        outflow = week_qs.filter(entry_type__in=OUTFLOW_TYPES).aggregate(total=Sum("amount"))["total"] or 0
        weekly_labels.append(week_start.strftime("%d %b"))
        weekly_inflow.append(float(inflow))
        weekly_outflow.append(float(outflow))

    return {
        "total_members": MemberProfile.objects.filter(status=MemberProfile.Status.ACTIVE).count(),
        "total_inflow": total_inflow,
        "total_outflow": total_outflow,
        "chart_labels": weekly_labels,
        "chart_inflow": weekly_inflow,
        "chart_outflow": weekly_outflow,
    }


def _active_members():
    from apps.accounts1.models import MemberProfile

    return [p.user for p in MemberProfile.objects.filter(status=MemberProfile.Status.ACTIVE).select_related("user")]


def _is_admin_tier(user):
    return user.is_authenticated and user.is_admin_tier


@login_required
@user_passes_test(_is_admin_tier)
@permission_required("core.view_auditlog", raise_exception=True)
def audit_log_view(request):
    """
    Read-only, filterable list of every admin/financial action (Section
    3B). Uses Django's default `view_auditlog` permission — auto-created
    for every model, no custom Meta.permissions entry needed for this one.
    """
    logs = AuditLog.objects.select_related("actor").all()

    action_filter = request.GET.get("action", "").strip()
    target_filter = request.GET.get("target_model", "").strip()
    actor_filter = request.GET.get("actor", "").strip()

    if action_filter:
        logs = logs.filter(action__icontains=action_filter)
    if target_filter:
        logs = logs.filter(target_model__icontains=target_filter)
    if actor_filter:
        logs = logs.filter(actor__username__icontains=actor_filter)

    paginator = Paginator(logs, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "core/audit_log.html",
        {
            "page_obj": page_obj,
            "action_filter": action_filter,
            "target_filter": target_filter,
            "actor_filter": actor_filter,
        },
    )
