
from typing import Any
from uuid import UUID

from apps.users.services import otp
from apps.users.tasks import send_verification_email


def handle_email_verification_requested(
    user_id: UUID,
    payload: dict[str, Any],
) -> None:
    email = payload["email"]

    verification_code = otp.generate_verification_code()

    otp.store_verification_code(
        user_id=user_id,
        code=verification_code,
    )

    send_verification_email.delay(
        email=email,
        verification_code=verification_code,
    )
