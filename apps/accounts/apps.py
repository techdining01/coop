from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"

    def ready(self):
        # Registers the role -> Group sync signal. Imported here,
        # not at module top-level, per Django's standard signal-registration
        # pattern — avoids app-loading-order issues.
        from. import signals  # noqa: F401
