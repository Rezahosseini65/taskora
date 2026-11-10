
import secrets

from django.conf import settings
from django.core.cache import caches
from django.utils.crypto import salted_hmac

from . import block


OTP_TTL = 10 * 60
OTP_LENGTH = 6

OTP_KEY_PREFIX = "taskora:users:email-verification:otp"


VERIFY_OTP_SCRIPT = """
if redis.call("EXISTS", KEYS[3]) == 1 then
    return -1
end

local stored_digest = redis.call("GET", KEYS[1])

if not stored_digest then
    return 0
end

if stored_digest == ARGV[1] then
    redis.call("DEL", KEYS[1])
    redis.call("DEL", KEYS[2])
    redis.call("DEL", KEYS[3])
    return 1
end

local attempts = redis.call("INCR", KEYS[2])

if attempts == 1 then
    redis.call("EXPIRE", KEYS[2], ARGV[2])
end

if attempts >= tonumber(ARGV[3]) then
    redis.call("SET", KEYS[3], "1", "EX", ARGV[4])
    redis.call("EXPIRE", KEYS[2], ARGV[4])
    return -1
end

return 0
"""


def _get_redis_client():
    return caches["default"].client.get_client(write=True)


def _get_otp_key(user_id):
    return f"{OTP_KEY_PREFIX}:{user_id}"


def _get_otp_digest(user_id, code):
    return salted_hmac(
        key_salt="users.email_verification.otp",
        value=f"{user_id}:{code}",
        secret=settings.SECRET_KEY,
        algorithm="sha256",
    ).hexdigest()


def generate_verification_code():
    return f"{secrets.randbelow(10 ** OTP_LENGTH):0{OTP_LENGTH}d}"


def store_verification_code(user_id, code):
    """
    Store the HMAC digest of a verification code in Redis.
    A new code replaces any previously stored code.
    """
    client = _get_redis_client()

    client.set(
        _get_otp_key(user_id),
        _get_otp_digest(user_id, code),
        ex=OTP_TTL,
    )


def verify_and_consume_verification_code(user_id, code):
    """
    Verify and consume an OTP atomically.

    Returns:
        1: OTP is valid and consumed.
        0: OTP is invalid or expired.
       -1: Account is temporarily locked.
    """
    client = _get_redis_client()

    result = client.eval(
        VERIFY_OTP_SCRIPT,
        3,
        _get_otp_key(user_id),
        block._get_attempts_key(user_id),
        block._get_lock_key(user_id),
        _get_otp_digest(user_id, code),
        block.OTP_ATTEMPTS_TTL,
        block.OTP_MAX_ATTEMPTS,
        block.OTP_LOCK_DURATION,
    )

    return int(result) if result != 1 else True
