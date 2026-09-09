import csv
import os

from django.contrib.auth.decorators import login_required, permission_required, user_passes_test
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from .models import LedgerExport, LedgerEntry
from .services import LedgerService


def _is_admin_tier(user):
    return user.is_authenticated and user.is_admin_tier


@login_required
@user_passes_test(_is_admin_tier)
@permission_required("ledger.can_view_ledger_exports", raise_exception=True)
def export_list_view(request):
    exports = LedgerExport.objects.all()[:26]  # ~6 months of weekly exports
    return render(request, "ledger/export_list.html", {"exports": exports})


@login_required
@user_passes_test(_is_admin_tier)
@permission_required("ledger.can_view_ledger_exports", raise_exception=True)
def export_download_view(request, pk):
    """
    Serves the file, and — only on the FIRST download — marks downloaded_by/
    downloaded_at and queues the cleanup task with a short delay (Section
    3C: cleanup is triggered by the download event, not a blind schedule).
    A re-download of an already-downloaded-but-not-yet-cleaned-up export
    just serves the file again without re-queuing cleanup or overwriting
    who/when it was first downloaded.
    """
    export = get_object_or_404(LedgerExport, pk=pk)

    if export.deleted_at is not None:
        raise Http404("This export has already been downloaded and cleaned up.")

    if not os.path.exists(export.file_path):
        raise Http404("Export file is missing on disk.")

    is_first_download = export.downloaded_at is None
    if is_first_download:
        export.downloaded_by = request.user
        export.downloaded_at = timezone.now()
        export.save(update_fields=["downloaded_by", "downloaded_at"])

        from .tasks import cleanup_downloaded_export

        # Countdown, not immediate: gives a slow connection time to finish
        # receiving the file before the cleanup task removes it from disk.
        cleanup_downloaded_export.apply_async(args=[export.pk], countdown=120)

    return FileResponse(open(export.file_path, "rb"), as_attachment=True, filename=os.path.basename(export.file_path))


# --- Phase 6: member-facing personal statement  ---
# On-demand, not persisted as a model (unlike LedgerExport) — this is a
# per-member document generated fresh on each request, with no cleanup
# tracking needed since it's a normal HTTP response, not a file sitting
# on disk afterward.

@login_required
def my_statement_pdf_view(request):
    from datetime import date

    from .exports import generate_member_statement_pdf

    pdf_bytes = generate_member_statement_pdf(request.user, date.today())
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="statement-{request.user.username}.pdf"'
    return response


@login_required
def my_statement_csv_view(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="statement-{request.user.username}.csv"'
    writer = csv.writer(response)
    writer.writerow(["Date", "Type", "Amount", "Balance After", "Source"])

    entries = LedgerEntry.objects.filter(
        member=request.user, loan__isnull=True, status=LedgerEntry.Status.CONFIRMED
    ).order_by("created_at")
    for entry in entries:
        writer.writerow(
            [
                entry.created_at.strftime("%Y-%m-%d %H:%M"),
                entry.get_entry_type_display(),
                entry.amount,
                entry.balance_after,
                entry.get_source_display(),
            ]
        )
    return response


# --- Phase 6: admin-facing bulk reports ---
# CSV, not Excel — kept dependency-light (no openpyxl) since CSV opens
# fine in Excel/Sheets and nothing in the design specifically called for
# native .xlsx. A reasonable follow-up if actually needed, not built here
# without being asked for it.

@login_required
@user_passes_test(_is_admin_tier)
@permission_required("core.can_view_reports", raise_exception=True)
def reports_index_view(request):
    return render(request, "ledger/reports_index.html")


@login_required
@user_passes_test(_is_admin_tier)
@permission_required("core.can_view_reports", raise_exception=True)
def report_member_statements_csv(request):
    from apps.accounts1.models import MemberProfile

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="member-statements.csv"'
    writer = csv.writer(response)
    writer.writerow(["Member", "Status", "Joined", "Savings Balance"])

    for profile in MemberProfile.objects.select_related("user").order_by("user__last_name"):
        writer.writerow(
            [
                profile.user.get_full_name() or profile.user.username,
                profile.get_status_display(),
                profile.joined_at.strftime("%Y-%m-%d"),
                LedgerService.get_savings_balance(profile.user),
            ]
        )
    return response


@login_required
@user_passes_test(_is_admin_tier)
@permission_required("core.can_view_reports", raise_exception=True)
def report_loan_book_csv(request):
    from apps.loans.models import Loan

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="loan-book.csv"'
    writer = csv.writer(response)
    writer.writerow(["Member", "Principal", "Financing Structure", "Status", "Applied", "Outstanding Balance"])

    for loan in Loan.objects.select_related("member").order_by("-applied_at"):
        outstanding = (
            LedgerService.get_loan_outstanding_balance(loan)
            if loan.status in (Loan.Status.ACTIVE, Loan.Status.COMPLETED)
            else ""
        )
        writer.writerow(
            [
                loan.member.get_full_name() or loan.member.username,
                loan.principal,
                loan.get_financing_structure_display(),
                loan.get_status_display(),
                loan.applied_at.strftime("%Y-%m-%d"),
                outstanding,
            ]
        )
    return response


@login_required
@user_passes_test(_is_admin_tier)
@permission_required("core.can_view_reports", raise_exception=True)
def report_savings_summary_csv(request):
    from apps.accounts1.models import MemberProfile

    active_profiles = MemberProfile.objects.filter(status=MemberProfile.Status.ACTIVE).select_related("user")
    balances = [LedgerService.get_savings_balance(p.user) for p in active_profiles]
    total = sum(balances) if balances else 0
    count = len(balances)
    average = (total / count) if count else 0

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="savings-summary.csv"'
    writer = csv.writer(response)
    writer.writerow(["Metric", "Value"])
    writer.writerow(["Active members", count])
    writer.writerow(["Total savings", total])
    writer.writerow(["Average savings balance", round(average, 2)])
    return response


@login_required
@user_passes_test(_is_admin_tier)
@permission_required("core.can_view_reports", raise_exception=True)
def report_overdue_csv(request):
    from apps.loans.models import RepaymentSchedule

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="overdue-installments.csv"'
    writer = csv.writer(response)
    writer.writerow(["Member", "Loan ID", "Installment", "Due Date", "Outstanding"])

    overdue = RepaymentSchedule.objects.filter(status=RepaymentSchedule.Status.OVERDUE).select_related("loan", "loan__member")
    for installment in overdue:
        writer.writerow(
            [
                installment.loan.member.get_full_name() or installment.loan.member.username,
                installment.loan_id,
                installment.installment_number,
                installment.due_date.strftime("%Y-%m-%d"),
                installment.outstanding,
            ]
        )
    return response
