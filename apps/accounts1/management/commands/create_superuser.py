from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

User = get_user_model()

DEFAULTS = {
    "DJANGO_SUPERUSER_USERNAME": "admin",
    "DJANGO_SUPERUSER_EMAIL": "admin@example.com",
    "DJANGO_SUPERUSER_PASSWORD": "admin123",
}


class Command(BaseCommand):
    help = "Create a superuser if one does not already exist."

    def handle(self, *args, **options):
        if User.objects.filter(is_superuser=True).exists():
            self.stdout.write(self.style.SUCCESS("Superuser already exists. Skipping."))
            return

        username = DEFAULTS["DJANGO_SUPERUSER_USERNAME"]
        email = DEFAULTS["DJANGO_SUPERUSER_EMAIL"]
        password = DEFAULTS["DJANGO_SUPERUSER_PASSWORD"]

        user = User.objects.create_superuser(
            username=username,
            email=email,
            password=password,
            role=User.Role.SUPERADMIN,
        )
        self.stdout.write(self.style.SUCCESS(f"Superuser '{user.username}' created successfully."))
