"""
Generates the weekly downloadable ledger PDF snapshot.
One combined admin-facing document — all confirmed transactions across all
members for the period — NOT the same as a member's personal statement
(that's a separate, member-facing feature not built in this phase).

Uses reportlab (pure Python, no system-level dependencies like cairo/pango)
rather than weasyprint/wkhtmltopdf, specifically to keep the Docker image
simple — see requirements.txt.
"""

import os
from datetime import date

from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

from .models import LedgerEntry


def generate_weekly_export_pdf(period_start: date, period_end: date) -> str:
    """
    Renders every CONFIRMED LedgerEntry in [period_start, period_end] to a
    PDF table, saves it under EXPORTS_ROOT, and returns the file path
    (relative path is what LedgerExport.file_path stores — see tasks.py).
    """
    os.makedirs(settings.EXPORTS_ROOT, exist_ok=True)
    filename = f"ledger-export-{period_start.isoformat()}-to-{period_end.isoformat()}.pdf"
    file_path = os.path.join(settings.EXPORTS_ROOT, filename)

    entries = (
        LedgerEntry.objects.filter(
            status=LedgerEntry.Status.CONFIRMED,
            created_at__date__gte=period_start,
            created_at__date__lte=period_end,
        )
        .select_related("member", "loan")
        .order_by("created_at")
    )

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(file_path, pagesize=landscape(A4), topMargin=15 * mm, bottomMargin=15 * mm)
    story = [
        Paragraph(f"Ledger Export — {period_start.strftime('%d %b %Y')} to {period_end.strftime('%d %b %Y')}", styles["Title"]),
        Spacer(1, 6 * mm),
    ]

    header = ["Date", "Member", "Type", "Loan #", "Amount (₦)", "Balance After (₦)", "Source", "Status"]
    rows = [header]
    for entry in entries:
        rows.append(
            [
                entry.created_at.strftime("%d %b %Y %H:%M"),
                entry.member.get_full_name() or entry.member.username,
                entry.get_entry_type_display(),
                str(entry.loan_id) if entry.loan_id else "—",
                f"{entry.amount:,.2f}",
                f"{entry.balance_after:,.2f}",
                entry.get_source_display(),
                entry.get_status_display(),
            ]
        )

    if len(rows) == 1:
        story.append(Paragraph("No confirmed transactions in this period.", styles["Normal"]))
    else:
        table = Table(rows, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph(f"Total transactions: {len(rows) - 1}", styles["Normal"]))

    doc.build(story)
    return file_path


def generate_member_statement_pdf(member, as_of: date) -> bytes:
    """
    A single member's personal savings statement ( — "for AGM or
    personal records"). Unlike the weekly admin export, this is generated
    fresh per request and rendered entirely IN MEMORY (io.BytesIO), not
    written to disk — a per-request temp file with no cleanup path would
    just accumulate on disk indefinitely across downloads, which is a real
    leak, not a hypothetical one. The caller (views.py) serves the
    returned bytes directly; nothing touches the filesystem.
    """
    import io

    from .services import LedgerService

    buffer = io.BytesIO()

    entries = (
        LedgerEntry.objects.filter(member=member, loan__isnull=True, status=LedgerEntry.Status.CONFIRMED)
        .order_by("created_at")
    )

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm)
    display_name = member.get_full_name() or member.username
    story = [
        Paragraph("Personal Savings Statement", styles["Title"]),
        Paragraph(f"{display_name} — as of {as_of.strftime('%d %b %Y')}", styles["Normal"]),
        Spacer(1, 6 * mm),
        Paragraph(f"Current balance: ₦{LedgerService.get_savings_balance(member):,.2f}", styles["Heading3"]),
        Spacer(1, 6 * mm),
    ]

    header = ["Date", "Type", "Amount (₦)", "Balance After (₦)"]
    rows = [header]
    for entry in entries:
        rows.append(
            [
                entry.created_at.strftime("%d %b %Y"),
                entry.get_entry_type_display(),
                f"{entry.amount:,.2f}",
                f"{entry.balance_after:,.2f}",
            ]
        )

    if len(rows) == 1:
        story.append(Paragraph("No transactions on record.", styles["Normal"]))
    else:
        table = Table(rows, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
                ]
            )
        )
        story.append(table)

    doc.build(story)
    return buffer.getvalue()
