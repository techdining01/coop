from django.contrib.auth import login as auth_login
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required, user_passes_test
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect, render
from django.urls import reverse_lazy

from .forms import MemberRegistrationForm
from .models import MemberProfile


class CoopLoginView(LoginView):
    template_name = "accounts/login.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "You have been successfully logged in!")
        return response


class CoopLogoutView(LogoutView):
    next_page = reverse_lazy("accounts:login")

    def dispatch(self, request, *args, **kwargs):
        if request.method == "GET":
            return render(request, "accounts/logout_confirm.html")
        messages.success(request, "You have been successfully logged out!")
        return super().dispatch(request, *args, **kwargs)


def _is_admin_tier(user):
    return user.is_authenticated and user.is_admin_tier


@login_required
@user_passes_test(_is_admin_tier)
@permission_required("accounts.can_approve_members", raise_exception=True)
def approve_members_view(request):
    """
    In-app equivalent of MemberProfileAdmin.approve_members — Secretary /
    Chairman can promote pending profiles to ACTIVE without going through
    Django admin. Same PayVessel reserved-account side-effect (queued
    async, never blocks the response).
    """
    pending = MemberProfile.objects.exclude(status=MemberProfile.Status.ACTIVE).select_related("user")

    if request.method == "POST":
        from apps.payments.tasks import create_reserved_account_task

        ids = request.POST.getlist("profile_ids")
        approved = 0
        for profile in pending.filter(pk__in=ids):
            profile.status = MemberProfile.Status.ACTIVE
            profile.save(update_fields=["status"])
            create_reserved_account_task.delay(profile.pk)
            approved += 1
        if approved:
            messages.success(request, f"Approved {approved} member(s). Reserved-account creation queued.")
        else:
            messages.warning(request, "No members selected.")
        return redirect("accounts:approve_members")

    return render(request, "accounts/approve_members.html", {"pending": pending})


def register_view(request):
    """
    Registration + admin-approval workflow. BVN/NIN verification against
    PayVessel's API is fired async from MemberRegistrationForm.save()
    (Section 5a) — it never blocks this view. Status starts as PENDING
    regardless of the verification result; an admin approves manually via
    Django admin (MemberProfileAdmin.approve_members), which is also what
    triggers PayVessel reserved account creation.
    """
    if request.method == "POST":
        form = MemberRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            return redirect("accounts:pending_approval")
    else:
        form = MemberRegistrationForm()
    return render(request, "accounts/register.html", {"form": form})


@login_required
def pending_approval_view(request):
    return render(request, "accounts/pending_approval.html")
