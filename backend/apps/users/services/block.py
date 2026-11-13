
import uuid

from django.core.cache import caches


OTP_MAX_ATTEMPTS = 5
OTP_LOCK_DURATION = 15 * 60
OTP_RESEND_COOLDOWN = 60
OTP_ATTEMPTS_TTL = 24 * 60 * 60

# Keep idempotency records long enough to cover Outbox retries.
RESEND_GENERATION_RECORD_TTL = 30 * 24 * 60 * 60

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
    return -1
end

return attempts
"""


START_RESEND_COOLDOWN_SCRIPT = """
if redis.call("EXISTS", KEYS[2]) == 1 then
    return false
end

if redis.call("EXISTS", KEYS[1]) == 1 then
    return false
end

redis.call("SET", KEYS[1], ARGV[1], "EX", ARGV[2])

return ARGV[1]
"""


CLEAR_RESEND_COOLDOWN_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
end

return 0
"""


ACTIVATE_RESEND_GENERATION_SCRIPT = """
local existing_generation = redis.call("GET", KEYS[2])

if existing_generation then
    return tonumber(existing_generation)
end

local current_generation = redis.call("GET", KEYS[1])

if not current_generation then
    return -1
end

local new_generation = redis.call("INCR", KEYS[1])

redis.call(
    "SET",
    KEYS[2],
    tostring(new_generation),
    "EX",
    ARGV[2]
)

return new_generation
"""


def _get_redis_client():
    return caches["default"].client.get_client(write=True)


def _get_attempts_key(user_id):
    return f"{BLOCK_KEY_PREFIX}:attempts:{user_id}"


def _get_lock_key(user_id):
    return f"{BLOCK_KEY_PREFIX}:lock:{user_id}"


def _get_resend_key(user_id):
    return f"{BLOCK_KEY_PREFIX}:resend:{user_id}"


def _get_generation_key(user_id):
    return f"{BLOCK_KEY_PREFIX}:generation:{user_id}"


def _get_resend_generation_key(user_id, request_id):
    return (
        f"{BLOCK_KEY_PREFIX}:resend-generation:"
        f"{user_id}:{request_id}"
    )


def initialize_generation(user_id):
    client = _get_redis_client()
    generation_key = _get_generation_key(user_id)

    client.set(generation_key, "1", nx=True)

    generation = client.get(generation_key)

    if generation is None:
        raise RuntimeError("Failed to initialize verification generation.")

    if isinstance(generation, bytes):
        generation = generation.decode("utf-8")

    return int(generation)


def is_account_locked(user_id):
    client = _get_redis_client()
    return bool(client.exists(_get_lock_key(user_id)))


def can_resend_verification_code(user_id):
    client = _get_redis_client()
    return not bool(client.exists(_get_resend_key(user_id)))


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


def start_resend_cooldown(user_id):
    """
    Reserve the resend cooldown without changing the OTP generation.

    Returns:
        str: Unique request ID when the reservation succeeds.
        None: The account is locked or a cooldown is already active.
    """
    client = _get_redis_client()
    request_id = uuid.uuid4().hex

    result = client.eval(
        START_RESEND_COOLDOWN_SCRIPT,
        2,
        _get_resend_key(user_id),
        _get_lock_key(user_id),
        request_id,
        OTP_RESEND_COOLDOWN,
    )

    if isinstance(result, bytes):
        result = result.decode("utf-8")

    return result or None


def clear_resend_cooldown(user_id, request_id):
    """
    Clear only the cooldown reservation belonging to this request.
    """
    client = _get_redis_client()

    return bool(
        client.eval(
            CLEAR_RESEND_COOLDOWN_SCRIPT,
            1,
            _get_resend_key(user_id),
            request_id,
        )
    )


def activate_resend_generation(user_id, request_id):
    """
    Activate a resend generation exactly once per request ID.

    Repeated calls for the same request return the original generation.
    """
    client = _get_redis_client()

    result = client.eval(
        ACTIVATE_RESEND_GENERATION_SCRIPT,
        2,
        _get_generation_key(user_id),
        _get_resend_generation_key(user_id, request_id),
        request_id,
        RESEND_GENERATION_RECORD_TTL,
    )

    result = int(result)

    if result < 1:
        raise RuntimeError(
            "Failed to activate email verification generation."
        )

    return result
