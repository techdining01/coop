"""
Reconciliation logic. Expects a CSV with, at minimum,
columns recognizable as a transaction reference and an amount — column
names are matched case-insensitively against a short list of likely
headers (see COLUMN_ALIASES) since the exact export format from
PayVessel's merchant dashboard wasn't confirmed against their docs for
this build (see the note on ReconciliationRun). If PayVessel's actual
export uses different headers, only COLUMN_ALIASES needs updating.
"""

import csv
import io
from decimal import Decimal, InvalidOperation

from django.db import transaction

from .models import ReconciliationDiscrepancy, ReconciliationRun, WebhookEvent

COLUMN_ALIASES = {
    "reference": {"reference", "transaction_reference", "trans_ref", "ref"},
    "amount": {"amount", "transaction_amount", "value"},
}


class ReconciliationError(Exception):
    pass


def _find_column(fieldnames, aliases):
    lowered = {f.strip().lower(): f for f in fieldnames}
    for alias in aliases:
        if alias in lowered:
            return lowered[alias]
    return None


class ReconciliationService:
    @staticmethod
    @transaction.atomic
    def run(*, csv_file, admin) -> ReconciliationRun:
        raw = csv_file.read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ReconciliationError("Could not read the file as UTF-8 CSV.") from exc

        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise ReconciliationError("File has no header row.")

        ref_col = _find_column(reader.fieldnames, COLUMN_ALIASES["reference"])
        amount_col = _find_column(reader.fieldnames, COLUMN_ALIASES["amount"])
        if not ref_col or not amount_col:
            raise ReconciliationError(
                "Could not find a reference and/or amount column. "
                f"Columns found: {', '.join(reader.fieldnames)}"
            )

        csv_file.seek(0)  # rewind so the FileField save below stores the original, unconsumed file
        run = ReconciliationRun.objects.create(uploaded_by=admin, source_file=csv_file)

        file_rows = {}  # reference -> Decimal amount
        total_rows = 0
        for row in reader:
            reference = (row.get(ref_col) or "").strip()
            if not reference:
                continue
            total_rows += 1
            try:
                file_rows[reference] = Decimal(str(row.get(amount_col, "0")).replace(",", "").strip())
            except InvalidOperation:
                ReconciliationDiscrepancy.objects.create(
                    run=run,
                    kind=ReconciliationDiscrepancy.Kind.AMOUNT_MISMATCH,
                    transaction_reference=reference,
                    notes=f"Unparseable amount in file: {row.get(amount_col)!r}",
                )

        local_events = {
            e.transaction_reference: e
            for e in WebhookEvent.objects.filter(status=WebhookEvent.Status.PROCESSED)
        }

        matched = 0
        discrepancies = []

        for reference, file_amount in file_rows.items():
            local_event = local_events.get(reference)
            if local_event is None:
                discrepancies.append(
                    ReconciliationDiscrepancy(
                        run=run,
                        kind=ReconciliationDiscrepancy.Kind.MISSING_LOCALLY,
                        transaction_reference=reference,
                        expected_amount=file_amount,
                        notes="PayVessel shows this transaction but no matching processed webhook was found locally.",
                    )
                )
                continue

            local_amount = local_event.resulting_ledger_entry.amount if local_event.resulting_ledger_entry else None
            if local_amount is not None and local_amount != file_amount:
                discrepancies.append(
                    ReconciliationDiscrepancy(
                        run=run,
                        kind=ReconciliationDiscrepancy.Kind.AMOUNT_MISMATCH,
                        transaction_reference=reference,
                        expected_amount=file_amount,
                        actual_amount=local_amount,
                        webhook_event=local_event,
                        notes="Amount in PayVessel's file differs from what was posted locally.",
                    )
                )
            else:
                matched += 1

        # Local PROCESSED events with no corresponding row in the file at all.
        for reference, local_event in local_events.items():
            if reference not in file_rows:
                discrepancies.append(
                    ReconciliationDiscrepancy(
                        run=run,
                        kind=ReconciliationDiscrepancy.Kind.MISSING_IN_FILE,
                        transaction_reference=reference,
                        actual_amount=local_event.resulting_ledger_entry.amount if local_event.resulting_ledger_entry else None,
                        webhook_event=local_event,
                        notes="Processed locally but not present in the uploaded PayVessel file.",
                    )
                )

        ReconciliationDiscrepancy.objects.bulk_create(discrepancies)

        run.total_rows_in_file = total_rows
        run.matched_count = matched
        run.discrepancy_count = len(discrepancies)
        run.save(update_fields=["total_rows_in_file", "matched_count", "discrepancy_count"])

        return run
