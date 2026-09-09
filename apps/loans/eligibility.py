"""
Section 6 — Loan Eligibility Rules. Two things layered here:

  1. The Shared Capital gate — a single, cooperative-wide, yes/no
     prerequisite checked BEFORE any tier, regardless of tenure or savings
     (LedgerService.has_paid_share_capital, from Phase 1 — Phase 4 is the
     first thing that actually calls it).
  2. The chosen LoanEligibilityPolicy tier's tenure/savings/cap rules,
     checked only once the gate above passes.

django-waffle controls whether this WHOLE check runs at all — a single
switch, not per-rule flags. See ENFORCE_SWITCH_NAME below.
"""

from dataclasses import dataclass

import waffle

from apps.ledger.services import LedgerService

from .models import LoanEligibilityPolicy

ENFORCE_SWITCH_NAME = "enforce_loan_eligibility_rules"


class IneligibleError(Exception):
    """Raised with a plain-language reason a member can read directly (Section 6)."""


@dataclass
class EligibilitySnapshot:
    """What LoanService/templates need to show/act on — computed once, reused."""

    enforced: bool
    has_paid_share_capital: bool
    membership_duration_months: float
    savings_balance: object  # Decimal — typed loosely to avoid importing Decimal just for the hint


class EligibilityService:
    @staticmethod
    def is_enforced() -> bool:
        """
        The switch, and only the switch, controls whether the checks below
        run at all. WAFFLE_SWITCH_DEFAULT=True (settings.py) means an
        admin who has never touched Django admin's "Switches" page still
        gets enforcement ON by default, matching Section 6's stated default.
        """
        return waffle.switch_is_active(ENFORCE_SWITCH_NAME)

    @staticmethod
    def snapshot(member) -> EligibilitySnapshot:
        """Read-only view of where a member stands — used by both the check below and the application template (-- show why, before they even submit)."""
        profile = getattr(member, "member_profile", None)
        duration_months = (profile.membership_duration_days / 30) if profile else 0
        return EligibilitySnapshot(
            enforced=EligibilityService.is_enforced(),
            has_paid_share_capital=LedgerService.has_paid_share_capital(member),
            membership_duration_months=duration_months,
            savings_balance=LedgerService.get_savings_balance(member),
        )

    @staticmethod
    def check(*, member, policy: LoanEligibilityPolicy, principal):
        """
        Raises IneligibleError with a plain-language reason if the member
        doesn't qualify. Returns None (silently) if eligible OR if
        enforcement is switched off — LoanService treats "no exception" as
        "proceed", so a disabled switch is transparent to the caller.
        """
        if not EligibilityService.is_enforced():
            return  # switch off — admin applies judgment manually instead (Section 6)

        # 1. Shared Capital gate — checked first, stops here if it fails.
        if not LedgerService.has_paid_share_capital(member):
            raise IneligibleError(
                "You need to complete your Shared Capital contribution before applying for a loan."
            )

        # 2. Tenure, against the chosen tier.
        snapshot = EligibilityService.snapshot(member)
        if snapshot.membership_duration_months < policy.min_tenure_months:
            months_needed = policy.min_tenure_months - snapshot.membership_duration_months
            raise IneligibleError(
                f"You need {months_needed:.0f} more month(s) of membership to qualify for {policy.name}."
            )

        # 3. Savings balance, against the chosen tier.
        if snapshot.savings_balance < policy.min_savings_balance:
            shortfall = policy.min_savings_balance - snapshot.savings_balance
            raise IneligibleError(
                f"You need ₦{shortfall:.2f} more in savings to qualify for {policy.name}."
            )

        # 4. Requested amount, against that tier's cap relative to savings.
        cap = snapshot.savings_balance * policy.max_loan_multiple
        if principal > cap:
            raise IneligibleError(
                f"The maximum loan amount under {policy.name} is ₦{cap:.2f} "
                f"({policy.max_loan_multiple}x your current savings balance)."
            )
