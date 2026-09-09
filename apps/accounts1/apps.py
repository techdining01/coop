from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"

    def ready(self):
        # Registers the role -> Group sync signal . Imported here,
       
        from . import signals  # noqa: F401
