from django.apps import AppConfig


class BlackjackConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "blackjack"
    verbose_name = "Blackjack"

    def ready(self):
        from . import signals  # noqa: F401
