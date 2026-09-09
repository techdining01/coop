from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import KYCVerification, MemberProfile, User





@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "email", "role", "is_active", "date_joined")
    list_filter = ("role", "is_active")
    fieldsets = BaseUserAdmin.fieldsets + (("Role", {"fields": ("role", "phone_number")}),)


@admin.register(MemberProfile)
class MemberProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "status", "id_type", "latest_kyc_status", "payvessel_account_number", "payvessel_error_count", "joined_at")
    list_filter = ("status", "id_type")
    search_fields = ("user__username", "user__first_name", "user__last_name")
    readonly_fields = ("joined_at", "payvessel_account_number", "payvessel_bank_name", "payvessel_error", "payvessel_error_count")
    actions = ["approve_members"]

    def latest_kyc_status(self, obj):
        latest = obj.user.kyc_verifications.first()  # ordered -created_at
        return latest.match_status if latest else "—"

    latest_kyc_status.short_description = "KYC match"

    def get_actions(self, request):
        """
        Phase 6: hide the approve action entirely from admins without the
        can_approve_members permission (Secretary/Chairman by default —
        see setup_roles.py), rather than showing it and failing silently
        or erroring after the fact.
        """
        actions = super().get_actions(request)
        if not request.user.has_perm("accounts.can_approve_members"):
            actions.pop("approve_members", None)
        return actions

    def approve_members(self, request, queryset):
        """
        Sets status=ACTIVE and create reserved-account("On admin approval: PayVessel reserved (STATIC) virtual account
        created"). Deliberately does NOT check KYC match status here —
        an admin may have legitimate reasons to approve despite a flagged
        mismatch., "flagged... for manual follow-up", not an
        automatic block), so this is a judgment call left to the admin,
        not enforced in code.
        """
        from apps.payments.tasks import create_reserved_account_task

        updated = 0
        for profile in queryset.exclude(status=MemberProfile.Status.ACTIVE):
            profile.status = MemberProfile.Status.ACTIVE
            profile.save(update_fields=["status"])
            create_reserved_account_task.delay(profile.pk)
            updated += 1
        self.message_user(request, f"Approved {updated} member(s). Reserved account creation queued.")

    approve_members.short_description = "Approve selected members (activates + creates PayVessel account)"


@admin.register(KYCVerification)
class KYCVerificationAdmin(admin.ModelAdmin):
    list_display = ("member", "id_type", "match_status", "verified_at", "created_at")
    list_filter = ("id_type", "match_status")
    search_fields = ("member__username",)
    readonly_fields = [f.name for f in KYCVerification._meta.fields]  # a verification result, never hand-edited

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
