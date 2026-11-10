
from django.core.cache import caches


OTP_MAX_ATTEMPTS = 5
OTP_LOCK_DURATION = 15 * 60
OTP_RESEND_COOLDOWN = 60
OTP_ATTEMPTS_TTL = 24 * 60 * 60

BLOCK_KEY_PREFIX = "taskora:users:email-verification"


INCREMENT_ATTEMPTS_SCRIPT = """
if redis.call("EXISTS", KEYS[2]) == 1 then
    return -1
end

local current_attempts = redis.call("GET", KEYS[1])

if current_attempts and tonumber(current_attempts) >= tonumber(ARGV[2]) then
    redis.call("DEL", KEYS[1])
end

local attempts = redis.call("INCR", KEYS[1])

if attempts == 1 then
    redis.call("EXPIRE", KEYS[1], ARGV[1])
end

if attempts >= tonumber(ARGV[2]) then
    redis.call("SET", KEYS[2], "1", "EX", ARGV[3])
    redis.call("EXPIRE", KEYS[1], ARGV[3])
end

return attempts
"""


START_RESEND_COOLDOWN_SCRIPT = """
if redis.call("EXISTS", KEYS[2]) == 1 then
    return -1
end

local result = redis.call(
    "SET",
    KEYS[1],
    "1",
    "EX",
    ARGV[1],
    "NX"
)

if result then
    return 1
end

return 0
"""


def _get_redis_client():
    return caches["default"].client.get_client(write=True)


def _get_attempts_key(user_id):
    return f"{BLOCK_KEY_PREFIX}:attempts:{user_id}"


def _get_lock_key(user_id):
    return f"{BLOCK_KEY_PREFIX}:lock:{user_id}"


def _get_resend_key(user_id):
    return f"{BLOCK_KEY_PREFIX}:resend:{user_id}"


def is_account_locked(user_id):
    client = _get_redis_client()
    return bool(client.exists(_get_lock_key(user_id)))


def increment_failed_attempts(user_id):
    client = _get_redis_client()

    result = client.eval(
        INCREMENT_ATTEMPTS_SCRIPT,
        2,
        _get_attempts_key(user_id),
        _get_lock_key(user_id),
        OTP_ATTEMPTS_TTL,
        OTP_MAX_ATTEMPTS,
        OTP_LOCK_DURATION,
    )

    return int(result)


def reset_failed_attempts(user_id):
    client = _get_redis_client()

    client.delete(
        _get_attempts_key(user_id),
        _get_lock_key(user_id),
    )


def can_resend_verification_code(user_id):
    client = _get_redis_client()
    return not bool(client.exists(_get_resend_key(user_id)))


def start_resend_cooldown(user_id):
    client = _get_redis_client()

    result = client.eval(
        START_RESEND_COOLDOWN_SCRIPT,
        2,
        _get_resend_key(user_id),
        _get_lock_key(user_id),
        OTP_RESEND_COOLDOWN,
    )

    return result == 1
