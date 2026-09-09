from django import forms

from apps.accounts.models import MemberProfile, User

from .models import LoanEligibilityPolicy


class LoanApplicationForm(forms.Form):
    policy = forms.ModelChoiceField(
        queryset=LoanEligibilityPolicy.objects.filter(is_active=True),
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Loan tier",
        help_text="Which tier you're applying under — determines the tenure/savings requirements and the cap.",
    )
    principal = forms.DecimalField(
        max_digits=14, decimal_places=2, min_value=0.01,
        widget=forms.NumberInput(attrs={"class": "form-input", "step": "0.01"}),
    )
    tenure_months = forms.IntegerField(
        min_value=1, max_value=60,
        widget=forms.NumberInput(attrs={"class": "form-input"}),
    )
    purpose = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )
    guarantor = forms.ModelChoiceField(
        queryset=User.objects.none(),  # set per-request in __init__ — excludes the applicant themselves
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text="Optional. If set, they must accept before your application is reviewed.",
    )

    def __init__(self, *args, applicant=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = User.objects.filter(role=User.Role.MEMBER, member_profile__status=MemberProfile.Status.ACTIVE)
        if applicant is not None:
            qs = qs.exclude(pk=applicant.pk)
        self.fields["guarantor"].queryset = qs

    def clean(self):
        cleaned = super().clean()
        return cleaned


class LoanRejectionForm(forms.Form):
    reason = forms.CharField(widget=forms.Textarea(attrs={"class": "form-input", "rows": 2}))


class RecordRepaymentForm(forms.Form):
    amount = forms.DecimalField(
        max_digits=14, decimal_places=2, min_value=0.01,
        widget=forms.NumberInput(attrs={"class": "form-input", "step": "0.01"}),
    )
    note = forms.CharField(required=False, max_length=255, widget=forms.TextInput(attrs={"class": "form-input"}))
