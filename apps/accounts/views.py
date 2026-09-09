from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required, permission_required, user_passes_test
from django.contrib.auth.views import LoginView
from django.shortcuts import get_object_or_404, redirect, render

from.forms import MemberRegistrationForm
from.models import MemberProfile


class CoopLoginView(LoginView):
    template_name = "accounts/login.html"


@login_required
def logout_view(request):
    """
    Separate confirmation step before logging out — GET shows "are you
    sure?", POST actually performs the logout. Written as an explicit
    function view rather than relying on Django's built-in LogoutView,
    since its GET/POST handling has changed across Django versions and
    an explicit two-step flow here is easier to reason about without
    being able to run the app to verify version-specific behavior.
    """
    if request.method == "POST":
        auth_logout(request)
        return redirect("accounts:login")
    return render(request, "accounts/logout_confirm.html")


def register_view(request):
    """
    Registration + admin-approval workflow. BVN/NIN verification against
    PayVessel's API is fired async from MemberRegistrationForm.save() — it never blocks this view. Status starts as PENDING
    regardless of the verification result; an admin approves via the
    in-app approval queue (member_approval_queue_view below) or Django
    admin's "Approve selected members" action — either way, approval is
    what triggers PayVessel reserved account creation.
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


def _is_admin_tier(user):
    return user.is_authenticated and user.is_admin_tier


@login_required
@user_passes_test(_is_admin_tier)
@permission_required("accounts.can_approve_members", raise_exception=True)
def member_approval_queue_view(request):
    """
    In-app equivalent of MemberProfileAdmin.approve_members — previously
    the ONLY way to approve a new member was Django's own /admin/, which
    isn't accessible to every admin tier and doesn't match the rest of
    this app's UI. Same permission gate as the Django admin action
    (accounts.can_approve_members), so a Secretary/Chairman can now do
    this without ever touching /admin/.
    """
    profiles = (
        MemberProfile.objects.filter(status=MemberProfile.Status.PENDING).select_related("user").prefetch_related("user__kyc_verifications").order_by("joined_at")
    )
    return render(request, "accounts/member_approval_queue.html", {"profiles": profiles})


@login_required
@user_passes_test(_is_admin_tier)
@permission_required("accounts.can_approve_members", raise_exception=True)
def member_approval_detail_view(request, pk):
    profile = get_object_or_404(MemberProfile, pk=pk, status=MemberProfile.Status.PENDING)
    latest_kyc = profile.user.kyc_verifications.first()  # ordered -created_at

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "approve":
            from apps.payments.tasks import create_reserved_account_task

            profile.status = MemberProfile.Status.ACTIVE
            profile.save(update_fields=["status"])
            create_reserved_account_task.delay(profile.pk)
            return redirect("accounts:member_approval_queue")
        elif action == "reject":
            reason = request.POST.get("rejection_reason", "").strip()
            if not reason:
                return render(
                    request,
                    "accounts/member_approval_detail.html",
                    {"profile": profile, "latest_kyc": latest_kyc, "error": "A rejection reason is required."},
                )
            profile.status = MemberProfile.Status.REJECTED
            profile.rejection_reason = reason
            profile.save(update_fields=["status", "rejection_reason"])
            return redirect("accounts:member_approval_queue")

    return render(request, "accounts/member_approval_detail.html", {"profile": profile, "latest_kyc": latest_kyc})
