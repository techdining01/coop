from django.contrib.auth.decorators import login_required, permission_required, user_passes_test
from django.shortcuts import render

from apps.ledger.models import LedgerEntry
from apps.ledger.services import LedgerError, LedgerService

from .forms import ManualEntryForm


def _is_admin_tier(user):
    return user.is_authenticated and user.is_admin_tier


@login_required
@user_passes_test(_is_admin_tier)
@permission_required("ledger.can_record_manual_transaction", raise_exception=True)
def manual_entry_view(request):
    """
    GET: render the form + recent entries.
    POST (HTMX): validate, post to the ledger, return the updated recent-
    entries partial plus an out-of-band toast — no full page reload.
    """
    if request.method == "POST":
        form = ManualEntryForm(request.POST)
        if form.is_valid():
            try:
                LedgerService.post_savings_entry(
                    member=form.cleaned_data["member"],
                    entry_type=form.cleaned_data["entry_type"],
                    amount=form.cleaned_data["amount"],
                    source=LedgerEntry.Source.MANUAL,
                    created_by=request.user,
                    note=form.cleaned_data["note"],
                )
                recent_entries = _recent_entries()
                return render(
                    request,
                    "transactions/_manual_entry_result.html",
                    {
                        "form": ManualEntryForm(),
                        "recent_entries": recent_entries,
                        "toast_message": "Deposit recorded.",
                        "toast_kind": "success",
                    },
                )
            except LedgerError as exc:
                return render(
                    request,
                    "transactions/_manual_entry_result.html",
                    {
                        "form": form,
                        "recent_entries": _recent_entries(),
                        "toast_message": str(exc),
                        "toast_kind": "error",
                    },
                    status=422,
                )
        else:
            return render(
                request,
                "transactions/_manual_entry_result.html",
                {
                    "form": form,
                    "recent_entries": _recent_entries(),
                    "toast_message": "Please fix the errors below.",
                    "toast_kind": "error",
                },
                status=422,
            )

    return render(
        request,
        "transactions/manual_entry.html",
        {"form": ManualEntryForm(), "recent_entries": _recent_entries()},
    )


def _recent_entries(limit=15):
    return (
        LedgerEntry.objects.filter(source=LedgerEntry.Source.MANUAL)
        .select_related("member", "created_by")
        .order_by("-created_at")[:limit]
    )
