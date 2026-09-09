from django.contrib import admin

from .models import Loan, LoanEligibilityPolicy, RepaymentSchedule


class RepaymentScheduleInline(admin.TabularInline):
    model = RepaymentSchedule
    extra = 0
    readonly_fields = ("installment_number", "due_date", "expected_amount", "paid_amount", "status", "paid_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(LoanEligibilityPolicy)
class LoanEligibilityPolicyAdmin(admin.ModelAdmin):
    """
    Where the committee edits tiers without a code change (Section 6).
    Enforcement is a separate concern — see django-waffle's "Switches"
    page in admin for enforce_loan_eligibility_rules.
    """

    list_display = ("name", "min_tenure_months", "min_savings_balance", "max_loan_multiple", "is_active")
    list_filter = ("is_active",)


@admin.register(Loan)
class LoanAdmin(admin.ModelAdmin):
    list_display = ("member", "policy", "principal", "status", "guarantor", "applied_at")
    list_filter = ("status", "policy")
    search_fields = ("member__username",)
    readonly_fields = ("applied_at", "reviewed_by", "reviewed_at", "disbursed_at")
    inlines = [RepaymentScheduleInline]
