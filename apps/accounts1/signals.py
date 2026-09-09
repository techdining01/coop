"""
Keeps a user's Django Group membership in sync with their `role` field,
so the simple role dropdown (used everywhere else in the app — templates,
is_admin_tier, registration) stays the single source of truth, while the
actual permission enforcement goes through Django's real Group/Permission
system underneath (Phase 6). A role change via Django admin or code
immediately updates which group(s) the user is in.

MEMBER and SUPERADMIN intentionally map to no group: a member has no
elevated Django permissions at all (correct — the app's own
`is_admin_tier`/view-level checks already gate what little a member-role
user could otherwise reach), and a superadmin is expected to be a real
Django `is_superuser`, which bypasses Group/Permission checks entirely
regardless of group membership (see setup_roles.py's docstring).
"""

from django.contrib.auth.models import Group
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import User

ROLE_TO_GROUP_NAME = {
    User.Role.TREASURER: "Treasurer",
    User.Role.SECRETARY: "Secretary",
    User.Role.CHAIRMAN: "Chairman",
}


@receiver(post_save, sender=User)
def sync_role_to_group(sender, instance, **kwargs):
    matching_group_name = ROLE_TO_GROUP_NAME.get(instance.role)

    # Remove from any of these three groups the user might currently be
    # in but shouldn't be anymore (e.g. role changed from Treasurer to
    # Secretary) — never touches groups outside this known set, so a
    # cooperative that's added its own custom groups isn't affected.
    known_groups = Group.objects.filter(name__in=ROLE_TO_GROUP_NAME.values())
    instance.groups.remove(*known_groups.exclude(name=matching_group_name))

    if matching_group_name:
        group, _ = Group.objects.get_or_create(name=matching_group_name)
        instance.groups.add(group)
