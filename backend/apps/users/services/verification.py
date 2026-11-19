from uuid import UUID

from django.core import signing


VERIFICATION_TOKEN_SALT = "users.email_verification"
VERIFICATION_TOKEN_MAX_AGE = 24 * 60 * 60


def generate_verification_token(user_id: UUID) -> str:
    """
    Generate a signed temporary token for email verification.
    """
    return signing.dumps(
        {"user_id": str(user_id)},
        salt=VERIFICATION_TOKEN_SALT,
        compress=True,
    )


def verify_verification_token(token: str) -> UUID | None:
    """
    Validate a verification token and return its associated user ID.
    """
    try:
        payload = signing.loads(
            token,
            salt=VERIFICATION_TOKEN_SALT,
            max_age=VERIFICATION_TOKEN_MAX_AGE,
        )

        return UUID(payload["user_id"])

    except (
        signing.BadSignature,
        signing.SignatureExpired,
        KeyError,
        TypeError,
        ValueError,
        AttributeError,
    ):
        return None
