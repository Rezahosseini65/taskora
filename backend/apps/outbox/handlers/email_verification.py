
from typing import Any
from uuid import UUID

from apps.users.services import block, otp
from apps.users.tasks import send_verification_email


def handle_email_verification_requested(
    user_id: UUID,
    payload: dict[str, Any],
) -> None:
    email = payload["email"]

    if "request_id" in payload:
        generation = block.activate_resend_generation(
            user_id=user_id,
            request_id=payload["request_id"],
        )
    else:
        generation = payload["generation"]

    verification_code = otp.generate_verification_code()

    stored = otp.store_verification_code(
        user_id=user_id,
        code=verification_code,
        generation=generation,
    )

    if not stored:
        return

    send_verification_email.delay(
        email=email,
        verification_code=verification_code,
        user_id=str(user_id),
        generation=generation,
    )
