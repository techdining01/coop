from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required, permission_required, user_passes_test
from django.contrib.auth.views import LoginView
from django.core.paginator import Paginator
from django.db import models
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .forms import MemberRegistrationForm
from .models import MemberProfile, User


class CoopLoginView(LoginView):
    template_name = "accounts/login.html"


@require_http_methods(["POST"])
def identity_lookup(request):
    """
    Optional pre-check: verifies BVN/NIN against PayVessel using the actual
    name/DOB the member typed. Registration does NOT require this to succeed —
    the submit button is always enabled; this is informational only.
    """
    id_type = request.POST.get("id_type")
    id_number = request.POST.get("id_number")
    first_name = request.POST.get("first_name", "").strip()
    last_name = request.POST.get("last_name", "").strip()
    gender = request.POST.get("gender", "MALE")
    birthday = request.POST.get("birthday", "")
    phone_number = request.POST.get("phone_number", "").strip()

    if not id_type or not id_number:
        return JsonResponse({"ok": False, "error": "Please enter your ID type and number first."}, status=400)
    if id_type not in MemberProfile.IdType.values:
        return JsonResponse({"ok": False, "error": "Unknown ID type."}, status=400)

    # PayVessel requires first_name and last_name to be at least 2 characters.
    # Fall back to placeholders only if the member hasn't filled those fields yet.
    first_name = first_name if len(first_name) >= 2 else "NA"
    last_name = last_name if len(last_name) >= 2 else "NA"
    phone_number = phone_number if phone_number else "08000000000"
    birthday = birthday if birthday else "1990-01-01"

    from apps.payments.client import PayVesselClient, PayVesselError

    client = PayVesselClient()
    common_kwargs = dict(
        first_name=first_name,
        last_name=last_name,
        middle_name="",
        gender=gender if gender in ("MALE", "FEMALE") else "MALE",
        birthday=birthday,
        phone_number=phone_number,
    )

    try:
        if id_type == MemberProfile.IdType.NIN:
            data = client.verify_nin(nin=id_number, **common_kwargs)
        else:
            data = client.verify_bvn(bvn=id_number, **common_kwargs)
        return JsonResponse({"ok": True, "data": data})
    except PayVesselError as exc:
        raw = str(exc)
        # Translate common PayVessel API errors into plain language
        if "422" in raw:
            friendly = "The ID number format is invalid. Please check and try again."
        elif "401" in raw or "403" in raw:
            friendly = "Verification service is temporarily unavailable. You can still register — an admin will review your ID manually."
        elif "404" in raw:
            friendly = "This ID number was not found in the verification database. Please double-check the number."
        elif "Network error" in raw:
            friendly = "Could not reach the verification service. Check your internet connection and try again."
        else:
            friendly = "Verification could not be completed right now. You can still register — your ID will be reviewed by an admin."
        return JsonResponse({"ok": False, "error": friendly}, status=200)  # 200 so JS always parses it


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
            return redirect("accounts:approve_members")
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
            return redirect("accounts:approve_members")

    return render(request, "accounts/member_approval_detail.html", {"profile": profile, "latest_kyc": latest_kyc})


@login_required
@user_passes_test(_is_admin_tier)
def user_management_view(request):
    """
    In-app user management: list all users, change role, suspend/activate/exit.
    Superadmin-only for role changes; any admin tier can suspend/activate members.
    """
    if request.method == "POST":
        user_id = request.POST.get("user_id")
        action = request.POST.get("action")
        target = get_object_or_404(User, pk=user_id)
        profile = getattr(target, "member_profile", None)

        if action == "suspend" and profile:
            profile.status = MemberProfile.Status.SUSPENDED
            profile.save(update_fields=["status"])
        elif action == "activate" and profile:
            profile.status = MemberProfile.Status.ACTIVE
            profile.save(update_fields=["status"])
        elif action == "exit" and profile:
            profile.status = MemberProfile.Status.EXITED
            profile.save(update_fields=["status"])
        elif action == "change_role" and request.user.is_superuser:
            new_role = request.POST.get("role")
            if new_role in User.Role.values:
                target.role = new_role
                target.save(update_fields=["role"])
        return redirect("accounts:user_management")

    status_filter = request.GET.get("status", "")
    role_filter = request.GET.get("role", "")
    search = request.GET.get("q", "").strip()

    users = User.objects.select_related("member_profile").order_by("-date_joined")
    if search:
        users = users.filter(
            models.Q(username__icontains=search)
            | models.Q(first_name__icontains=search)
            | models.Q(last_name__icontains=search)
            | models.Q(email__icontains=search)
        )
    if role_filter:
        users = users.filter(role=role_filter)
    if status_filter:
        users = users.filter(member_profile__status=status_filter)

    paginator = Paginator(users, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "accounts/user_management.html", {
        "page_obj": page_obj,
        "role_choices": User.Role.choices,
        "status_choices": MemberProfile.Status.choices,
        "status_filter": status_filter,
        "role_filter": role_filter,
        "search": search,
    })
