from uuid import UUID, uuid4

from django.conf import settings
from django.core import signing
from django.utils.crypto import salted_hmac

from django_redis import get_redis_connection


PASSWORD_RESET_TOKEN_SALT = "users.password_reset"
PASSWORD_RESET_TOKEN_MAX_AGE = 15 * 60
PASSWORD_RESET_TOKEN_TTL = PASSWORD_RESET_TOKEN_MAX_AGE

PASSWORD_RESET_REDIS_KEY_PREFIX = "users:password_reset"

CONSUME_PASSWORD_RESET_TOKEN_SCRIPT = """
local stored_digest = redis.call("GET", KEYS[1])

if stored_digest and stored_digest == ARGV[1] then
    redis.call("DEL", KEYS[1])
    return 1
end

return 0
"""


def _get_redis_client():
    return get_redis_connection("default")


def _get_password_reset_key(user_id: UUID) -> str:
    return f"{PASSWORD_RESET_REDIS_KEY_PREFIX}:{user_id}"


def _get_token_digest(token_id: str) -> str:
    return salted_hmac(
        key_salt=PASSWORD_RESET_TOKEN_SALT,
        value=token_id,
        secret=settings.SECRET_KEY,
    ).hexdigest()


def generate_password_reset_token(user_id: UUID) -> str:
    """
    Generate a signed, single-use password reset token.

    Only the token digest is stored in Redis.
    Generating a new token invalidates the previous token.
    """
    token_id = str(uuid4())

    token = signing.dumps(
        {
            "user_id": str(user_id),
            "token_id": token_id,
        },
        salt=PASSWORD_RESET_TOKEN_SALT,
        compress=True,
    )

    _get_redis_client().set(
        _get_password_reset_key(user_id),
        _get_token_digest(token_id),
        ex=PASSWORD_RESET_TOKEN_TTL,
    )

    return token


def get_password_reset_user_id(token: str) -> UUID | None:
    """
    Validate token signature, expiration, and current Redis state
    without consuming the token.
    """
    try:
        payload = signing.loads(
            token,
            salt=PASSWORD_RESET_TOKEN_SALT,
            max_age=PASSWORD_RESET_TOKEN_MAX_AGE,
        )

        user_id = UUID(payload["user_id"])
        token_id = str(UUID(payload["token_id"]))

    except (
        signing.BadSignature,
        signing.SignatureExpired,
        KeyError,
        TypeError,
        ValueError,
        AttributeError,
    ):
        return None

    stored_digest = _get_redis_client().get(
        _get_password_reset_key(user_id)
    )

    if stored_digest is None:
        return None

    if isinstance(stored_digest, bytes):
        stored_digest = stored_digest.decode("utf-8")

    if stored_digest != _get_token_digest(token_id):
        return None

    return user_id


def consume_password_reset_token(token: str) -> UUID | None:
    """
    Atomically validate and consume a password reset token.

    A token can only be consumed once. Issuing a newer token
    also invalidates every previously issued token for that user.
    """
    try:
        payload = signing.loads(
            token,
            salt=PASSWORD_RESET_TOKEN_SALT,
            max_age=PASSWORD_RESET_TOKEN_MAX_AGE,
        )

        user_id = UUID(payload["user_id"])
        token_id = str(UUID(payload["token_id"]))

    except (
        signing.BadSignature,
        signing.SignatureExpired,
        KeyError,
        TypeError,
        ValueError,
        AttributeError,
    ):
        return None

    result = _get_redis_client().eval(
        CONSUME_PASSWORD_RESET_TOKEN_SCRIPT,
        1,
        _get_password_reset_key(user_id),
        _get_token_digest(token_id),
    )

    if result != 1:
        return None

    return user_id