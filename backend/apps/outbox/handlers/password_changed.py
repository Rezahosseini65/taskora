from typing import Any
from uuid import UUID

from apps.users.tasks import send_password_changed_email


def handle_password_changed(
    user_id: UUID,
    payload: dict[str, Any],
) -> None:
    email = payload["email"]

    send_password_changed_email.delay(
        email=email,
    )