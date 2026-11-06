from django.apps import AppConfig, apps


class CommonConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "common"

    def ready(self):
        if apps.is_installed("drf_spectacular"):
            import common.authentication.schemas  # noqa: F401