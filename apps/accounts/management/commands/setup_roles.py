"""
Role-based admin tiers. This command creates/updates three Django Groups
with a REASONABLE DEFAULT permission mapping I came up with — not a spec
anyone handed me, since I was only told "different permission levels"
without being told exactly which action belongs to which tier. My
mapping is a sensible cooperative-society default (Treasurer = money
movement, Secretary = membership admin, Chairman = loan approval + both
oversight views), and I built it to be ADJUSTED via Django admin's
Groups UI afterward, not treated as fixed — that's the whole reason I
used Django's Group/Permission system instead of hardcoding checks in
Python.

I deliberately did NOT make Superadmin a Group — Django's real
`is_superuser` flag already bypasses every permission check
automatically. I'd pair User.role=SUPERADMIN with
is_superuser=True/is_staff=True via Django admin or createsuperuser;
the role field alone won't grant elevated access on its own, since every
permission check I added goes through Django's has_perm(), not the role
field directly.

Safe to re-run — get_or_create + set() makes this idempotent.
"""

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

ROLE_PERMISSIONS = {
    "Treasurer": [
        ("ledger", "can_record_manual_transaction"),
        ("ledger", "can_view_ledger_exports"),
        ("payments", "change_paymentproof"),  # receipt review (approve/reject)
        ("payments", "add_reconciliationrun"),  # running reconciliation
    ],
    "Secretary": [
        ("accounts", "can_approve_members"),
        ("core", "view_auditlog"),  # Django's default view_<model> permission
    ],
    "Chairman": [
        ("loans", "can_review_loans"),
        ("accounts", "can_approve_members"),
        ("core", "view_auditlog"),
        ("core", "can_view_reports"),
    ],
}


class Command(BaseCommand):
    help = "Create/update the Treasurer, Secretary, and Chairman permission groups."

    def handle(self, *args, **options):
        for group_name, perm_specs in ROLE_PERMISSIONS.items():
            group, created = Group.objects.get_or_create(name=group_name)
            permissions = []
            for app_label, codename in perm_specs:
                try:
                    permissions.append(Permission.objects.get(content_type__app_label=app_label, codename=codename))
                except Permission.DoesNotExist:
                    self.stderr.write(
                        self.style.WARNING(
                            f"Permission {app_label}.{codename} not found — run migrations first? Skipping."
                        )
                    )
            group.permissions.set(permissions)
            verb = "Created" if created else "Updated"
            self.stdout.write(self.style.SUCCESS(f"{verb} group '{group_name}' with {len(permissions)} permission(s)."))

        self.stdout.write(
            "\nGroups are ready. Users are added to the matching group automatically when their "
            "role field is set (see apps/accounts/signals.py) — or assign manually via Django admin."
        )
