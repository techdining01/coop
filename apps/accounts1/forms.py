from django import forms
from django.conf import settings
from django.contrib.auth.forms import UserCreationForm

from .models import MemberProfile, User


class MemberRegistrationForm(UserCreationForm):
    first_name = forms.CharField(max_length=150, widget=forms.TextInput(attrs={"class": "form-input"}))
    last_name = forms.CharField(max_length=150, widget=forms.TextInput(attrs={"class": "form-input"}))
    email = forms.EmailField(widget=forms.EmailInput(attrs={"class": "form-input"}))
    phone_number = forms.CharField(max_length=20, widget=forms.TextInput(attrs={"class": "form-input"}))
    date_of_birth = forms.DateField(widget=forms.DateInput(attrs={"class": "form-input", "type": "date"}))
    gender = forms.ChoiceField(choices=MemberProfile.Gender.choices, widget=forms.Select(attrs={"class": "form-select"}))
    id_type = forms.ChoiceField(
        choices=MemberProfile.IdType.choices,
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text="Verified your BVN/NIN before your membership is activated.",
    )
    id_number = forms.CharField(
        max_length=settings.BVN_LENGTH,
        min_length=settings.BVN_LENGTH,
        widget=forms.TextInput(attrs={"class": "form-input", "inputmode": "numeric"}),
    )

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "phone_number", "password1", "password2"]
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-input"}),
        }

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.MEMBER
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.email = self.cleaned_data["email"]
        user.phone_number = self.cleaned_data["phone_number"]
        if commit:
            user.save()
            profile = MemberProfile.objects.create(
                user=user,
                id_type=self.cleaned_data["id_type"],
                id_number=self.cleaned_data["id_number"],
                date_of_birth=self.cleaned_data["date_of_birth"],
                gender=self.cleaned_data["gender"],
                status=MemberProfile.Status.PENDING,
            )
            # Fire-and-forget: BVN/NIN verification runs async (Celery),
            # never blocks the registration response.
            from apps.payments.tasks import verify_identity_task

            verify_identity_task.delay(profile.pk)
        return user
