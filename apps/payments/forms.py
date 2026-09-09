from django import forms
from django.core.validators import FileExtensionValidator
from apps.ledger.models import LedgerEntry

from .models import PaymentProof


MAX_RECEIPT_SIZE_MB = 5


def validate_receipt_size(file):
    if file.size > MAX_RECEIPT_SIZE_MB * 1024 * 1024:
        raise forms.ValidationError(f"File too large — max {MAX_RECEIPT_SIZE_MB}MB.")


class ReceiptUploadForm(forms.ModelForm):
    file = forms.FileField(
        validators=[
            FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "pdf"]),
            validate_receipt_size,
        ],
        help_text="JPG, PNG, or PDF — max 5MB. Make sure the amount and date are legible.",
    )

    class Meta:
        model = PaymentProof
        fields = ["file", "claimed_type", "claimed_amount"]
        widgets = {
            "claimed_type": forms.Select(attrs={"class": "form-select"}),
            "claimed_amount": forms.NumberInput(attrs={"class": "form-input", "step": "0.01"}),
        }


class ReceiptReviewForm(forms.Form):
    """
    What the admin fills in after LOOKING AT the uploaded file themselves —
    no field here is pre-filled from any automated extraction. Defaults to
    the member's claimed values only as a starting point to edit, per
    Section 5c ("the admin is reading the image with their own eyes").
    """

    entry_type = forms.ChoiceField(
        choices=[
            (LedgerEntry.EntryType.DEPOSIT, "Savings Deposit"),
            (LedgerEntry.EntryType.SHARE_CAPITAL_CONTRIBUTION, "Share Capital Contribution"),
        ],
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    amount = forms.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=0.01,
        widget=forms.NumberInput(attrs={"class": "form-input", "step": "0.01"}),
    )


class ReconciliationUploadForm(forms.Form):
    csv_file = forms.FileField(
        validators=[FileExtensionValidator(allowed_extensions=["csv"])],
        help_text="CSV exported from your PayVessel merchant dashboard's settlement/transaction report.",
        widget=forms.ClearableFileInput(attrs={"accept": ".csv"}),
    )
