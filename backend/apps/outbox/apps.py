
from django.apps import AppConfig


class OutboxConfig(AppConfig):
    name = "apps.outbox"

    def ready(self):
        from apps.outbox.handlers.email_verification import (
            handle_email_verification_requested,
        )
        from apps.outbox.handlers.registry import registry

        registry.register(
            "users.email_verification_requested",
            handle_email_verification_requested,
        )

