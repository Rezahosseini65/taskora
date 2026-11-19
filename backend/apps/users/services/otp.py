
import secrets

from django.conf import settings
from django.core.cache import caches
from django.utils.crypto import salted_hmac

from . import block


OTP_TTL = 2 * 60
OTP_LENGTH = 6

OTP_KEY_PREFIX = "taskora:users:email-verification:otp"


STORE_OTP_SCRIPT = """
local current_generation = redis.call("GET", KEYS[2])

if not current_generation or current_generation ~= ARGV[1] then
    return 0
end

redis.call("SET", KEYS[1], ARGV[1] .. "|" .. ARGV[2], "EX", ARGV[3])

return 1
"""

IS_CURRENT_OTP_SCRIPT = """
local current_generation = redis.call("GET", KEYS[2])

if not current_generation or current_generation ~= ARGV[1] then
    return 0
end

local stored_value = redis.call("GET", KEYS[1])

if not stored_value then
    return 0
end

local stored_generation, stored_digest = string.match(
    stored_value,
    "^([^|]+)|(.+)$"
)

if stored_generation ~= ARGV[1] then
    return 0
end

if stored_digest == ARGV[2] then
    return 1
end

return 0
"""

VERIFY_OTP_SCRIPT = """
if redis.call("EXISTS", KEYS[3]) == 1 then
    return -1
end

local current_generation = redis.call("GET", KEYS[4])

if not current_generation or current_generation ~= ARGV[1] then
    return 0
end

local stored_value = redis.call("GET", KEYS[1])

if not stored_value then
    return 0
end

local stored_generation, stored_digest = string.match(
    stored_value,
    "^([^|]+)|(.+)$"
)

if stored_generation ~= ARGV[1] then
    return 0
end

if stored_digest == ARGV[2] then
    redis.call("DEL", KEYS[1])
    redis.call("DEL", KEYS[2])
    redis.call("DEL", KEYS[3])
    return 1
end

local attempts = redis.call("INCR", KEYS[2])

if attempts == 1 then
    redis.call("EXPIRE", KEYS[2], ARGV[3])
end

if attempts >= tonumber(ARGV[4]) then
    redis.call("SET", KEYS[3], "1", "EX", ARGV[5])
    redis.call("EXPIRE", KEYS[2], ARGV[5])
    return -1
end

return 0
"""


def _get_redis_client():
    return caches["default"].client.get_client(write=True)


def _get_otp_key(user_id):
    return f"{OTP_KEY_PREFIX}:{user_id}"


def _get_otp_digest(user_id, code, generation):
    return salted_hmac(
        key_salt="users.email_verification.otp",
        value=f"{user_id}:{generation}:{code}",
        secret=settings.SECRET_KEY,
        algorithm="sha256",
    ).hexdigest()


def generate_verification_code():
    return f"{secrets.randbelow(10 ** OTP_LENGTH):0{OTP_LENGTH}d}"


def store_verification_code(user_id, code, generation):
    """
    Store the HMAC digest of a verification code in Redis.

    The code is stored only if its generation is still current.

    Returns:
        True: The code was stored.
        False: The generation is outdated.
    """
    client = _get_redis_client()

    result = client.eval(
        STORE_OTP_SCRIPT,
        2,
        _get_otp_key(user_id),
        block._get_generation_key(user_id),
        str(generation),
        _get_otp_digest(user_id, code, generation),
        OTP_TTL,
    )

    return bool(result)

def is_verification_code_current(user_id, code, generation):
    """
    Check whether the OTP is still the current code for its generation.
    """
    client = _get_redis_client()

    result = client.eval(
        IS_CURRENT_OTP_SCRIPT,
        2,
        _get_otp_key(user_id),
        block._get_generation_key(user_id),
        str(generation),
        _get_otp_digest(user_id, code, generation),
    )

    return bool(result)

def verify_and_consume_verification_code(user_id, code):
    """
    Verify and consume an OTP atomically.

    Returns:
        True: OTP is valid and consumed.
        0: OTP is invalid, expired, or outdated.
       -1: Account is temporarily locked.
    """
    client = _get_redis_client()

    generation = client.get(block._get_generation_key(user_id))

    if generation is None:
        return 0

    if isinstance(generation, bytes):
        generation = generation.decode("utf-8")

    result = client.eval(
        VERIFY_OTP_SCRIPT,
        4,
        _get_otp_key(user_id),
        block._get_attempts_key(user_id),
        block._get_lock_key(user_id),
        block._get_generation_key(user_id),
        generation,
        _get_otp_digest(user_id, code, generation),
        block.OTP_ATTEMPTS_TTL,
        block.OTP_MAX_ATTEMPTS,
        block.OTP_LOCK_DURATION,
    )

    return int(result) if result != 1 else True
