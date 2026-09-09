from django import forms

from apps.accounts.models import MemberProfile, User
from apps.ledger.models import LedgerEntry


class ManualEntryForm(forms.Form):
    """
    Admin-facing fallback tool. Only savings-side entry types
    are offered — loan_disbursement/repayment/penalty aren't wired up until
    the Loan model exists.
    """

    ALLOWED_TYPES = [
        LedgerEntry.EntryType.DEPOSIT,
        LedgerEntry.EntryType.SHARE_CAPITAL_CONTRIBUTION,
    ]

    member = forms.ModelChoiceField(
        queryset=User.objects.filter(role=User.Role.MEMBER, member_profile__status=MemberProfile.Status.ACTIVE),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    entry_type = forms.ChoiceField(
        choices=[(t.value, t.label) for t in ALLOWED_TYPES],
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    amount = forms.DecimalField(
        max_digits=14,
        decimal_places=2,
        min_value=0.01,
        widget=forms.NumberInput(attrs={"class": "form-input", "step": "0.01"}),
    )
    note = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-input", "placeholder": "e.g. cash payment, receipt #1234"}),
    )
