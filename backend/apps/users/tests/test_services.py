import uuid

from django.test import TestCase

from apps.users.services import block, otp


class OTPServiceTests(TestCase):
    def setUp(self):
        self.user_id = uuid.uuid4()
        self.redis = otp._get_redis_client()
        self.otp_key = otp._get_otp_key(self.user_id)
        self.attempts_key = block._get_attempts_key(self.user_id)
        self.lock_key = block._get_lock_key(self.user_id)

    def tearDown(self):
        self.redis.delete(
            self.otp_key,
            self.attempts_key,
            self.lock_key,
        )

    def test_generate_verification_code_returns_six_digits(self):
        code = otp.generate_verification_code()

        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())

    def test_store_verification_code_stores_hmac_digest(self):
        code = "123456"

        otp.store_verification_code(self.user_id, code)

        stored_value = self.redis.get(self.otp_key)

        self.assertIsNotNone(stored_value)
        self.assertNotEqual(stored_value.decode(), code)
        self.assertEqual(
            stored_value.decode(),
            otp._get_otp_digest(self.user_id, code),
        )

    def test_store_verification_code_sets_expiration(self):
        otp.store_verification_code(self.user_id, "123456")

        ttl = self.redis.ttl(self.otp_key)

        self.assertGreater(ttl, 0)
        self.assertLessEqual(ttl, otp.OTP_TTL)

    def test_correct_code_is_verified_and_consumed(self):
        code = "123456"
        otp.store_verification_code(self.user_id, code)

        result = otp.verify_and_consume_verification_code(
            self.user_id,
            code,
        )

        self.assertIs(result, True)
        self.assertIsNone(self.redis.get(self.otp_key))

    def test_consumed_code_cannot_be_reused(self):
        code = "123456"
        otp.store_verification_code(self.user_id, code)

        first_result = otp.verify_and_consume_verification_code(
            self.user_id,
            code,
        )
        second_result = otp.verify_and_consume_verification_code(
            self.user_id,
            code,
        )

        self.assertIs(first_result, True)
        self.assertEqual(second_result, 0)

    def test_incorrect_code_does_not_consume_valid_code(self):
        otp.store_verification_code(self.user_id, "123456")

        result = otp.verify_and_consume_verification_code(
            self.user_id,
            "654321",
        )

        self.assertEqual(result, 0)
        self.assertIsNotNone(self.redis.get(self.otp_key))

    def test_incorrect_code_increments_attempt_counter(self):
        otp.store_verification_code(self.user_id, "123456")

        result = otp.verify_and_consume_verification_code(
            self.user_id,
            "654321",
        )

        self.assertEqual(result, 0)
        self.assertEqual(
            int(self.redis.get(self.attempts_key)),
            1,
        )

    def test_missing_code_does_not_increment_attempt_counter(self):
        result = otp.verify_and_consume_verification_code(
            self.user_id,
            "123456",
        )

        self.assertEqual(result, 0)
        self.assertFalse(self.redis.exists(self.attempts_key))

    def test_expired_code_cannot_be_verified(self):
        code = "123456"
        otp.store_verification_code(self.user_id, code)

        self.redis.delete(self.otp_key)

        result = otp.verify_and_consume_verification_code(
            self.user_id,
            code,
        )

        self.assertEqual(result, 0)
        self.assertFalse(self.redis.exists(self.attempts_key))

    def test_new_code_invalidates_previous_code(self):
        old_code = "123456"
        new_code = "654321"

        otp.store_verification_code(self.user_id, old_code)
        otp.store_verification_code(self.user_id, new_code)

        old_result = otp.verify_and_consume_verification_code(
            self.user_id,
            old_code,
        )
        new_result = otp.verify_and_consume_verification_code(
            self.user_id,
            new_code,
        )

        self.assertEqual(old_result, 0)
        self.assertIs(new_result, True)

    def test_fifth_incorrect_attempt_locks_account(self):
        otp.store_verification_code(self.user_id, "123456")

        for _ in range(4):
            result = otp.verify_and_consume_verification_code(
                self.user_id,
                "654321",
            )
            self.assertEqual(result, 0)

        result = otp.verify_and_consume_verification_code(
            self.user_id,
            "654321",
        )

        self.assertEqual(result, -1)
        self.assertTrue(block.is_account_locked(self.user_id))

    def test_locked_account_cannot_verify_correct_code(self):
        otp.store_verification_code(self.user_id, "123456")

        for _ in range(block.OTP_MAX_ATTEMPTS):
            otp.verify_and_consume_verification_code(
                self.user_id,
                "654321",
            )

        result = otp.verify_and_consume_verification_code(
            self.user_id,
            "123456",
        )

        self.assertEqual(result, -1)
        self.assertIsNotNone(self.redis.get(self.otp_key))

    def test_successful_verification_resets_attempts(self):
        otp.store_verification_code(self.user_id, "123456")

        otp.verify_and_consume_verification_code(
            self.user_id,
            "654321",
        )

        result = otp.verify_and_consume_verification_code(
            self.user_id,
            "123456",
        )

        self.assertIs(result, True)
        self.assertFalse(self.redis.exists(self.attempts_key))
        self.assertFalse(self.redis.exists(self.lock_key))

    def test_successful_verification_removes_existing_lock(self):
        otp.store_verification_code(self.user_id, "123456")

        self.redis.set(self.lock_key, "1", ex=block.OTP_LOCK_DURATION)
        self.redis.set(self.attempts_key, "5", ex=block.OTP_LOCK_DURATION)

        # A locked account must not be able to verify.
        locked_result = otp.verify_and_consume_verification_code(
            self.user_id,
            "123456",
        )
        self.assertEqual(locked_result, -1)

        # Simulate expiration of the temporary lock.
        self.redis.delete(self.lock_key, self.attempts_key)

        result = otp.verify_and_consume_verification_code(
            self.user_id,
            "123456",
        )

        self.assertIs(result, True)
        self.assertFalse(self.redis.exists(self.lock_key))
        self.assertFalse(self.redis.exists(self.attempts_key))


class OTPBlockServiceTests(TestCase):
    def setUp(self):
        self.user_id = uuid.uuid4()
        self.redis = block._get_redis_client()

        self.attempts_key = block._get_attempts_key(self.user_id)
        self.lock_key = block._get_lock_key(self.user_id)
        self.resend_key = block._get_resend_key(self.user_id)

    def tearDown(self):
        self.redis.delete(
            self.attempts_key,
            self.lock_key,
            self.resend_key,
        )

    def test_account_is_not_locked_initially(self):
        self.assertFalse(block.is_account_locked(self.user_id))

    def test_failed_attempts_are_incremented(self):
        for expected_attempt in range(1, 4):
            result = block.increment_failed_attempts(self.user_id)
            self.assertEqual(result, expected_attempt)

    def test_account_is_locked_after_maximum_failed_attempts(self):
        for _ in range(block.OTP_MAX_ATTEMPTS):
            block.increment_failed_attempts(self.user_id)

        self.assertTrue(block.is_account_locked(self.user_id))

    def test_locked_account_cannot_increment_attempts(self):
        for _ in range(block.OTP_MAX_ATTEMPTS):
            block.increment_failed_attempts(self.user_id)

        result = block.increment_failed_attempts(self.user_id)

        self.assertEqual(result, -1)

    def test_lock_has_expected_expiration(self):
        for _ in range(block.OTP_MAX_ATTEMPTS):
            block.increment_failed_attempts(self.user_id)

        ttl = self.redis.ttl(self.lock_key)

        self.assertGreater(ttl, 0)
        self.assertLessEqual(ttl, block.OTP_LOCK_DURATION)

    def test_attempt_counter_expires_after_lock_duration(self):
        for _ in range(block.OTP_MAX_ATTEMPTS):
            block.increment_failed_attempts(self.user_id)

        ttl = self.redis.ttl(self.attempts_key)

        self.assertGreater(ttl, 0)
        self.assertLessEqual(ttl, block.OTP_LOCK_DURATION)

    def test_attempts_can_start_again_after_lock_expires(self):
        for _ in range(block.OTP_MAX_ATTEMPTS):
            block.increment_failed_attempts(self.user_id)

        self.redis.delete(self.lock_key, self.attempts_key)

        result = block.increment_failed_attempts(self.user_id)

        self.assertEqual(result, 1)

    def test_reset_failed_attempts_removes_counter_and_lock(self):
        for _ in range(block.OTP_MAX_ATTEMPTS):
            block.increment_failed_attempts(self.user_id)

        block.reset_failed_attempts(self.user_id)

        self.assertFalse(self.redis.exists(self.attempts_key))
        self.assertFalse(block.is_account_locked(self.user_id))

    def test_account_can_resend_initially(self):
        self.assertTrue(block.can_resend_verification_code(self.user_id))

    def test_start_resend_cooldown_succeeds_once(self):
        first_result = block.start_resend_cooldown(self.user_id)
        second_result = block.start_resend_cooldown(self.user_id)

        self.assertTrue(first_result)
        self.assertFalse(second_result)

    def test_resend_cooldown_has_expected_expiration(self):
        block.start_resend_cooldown(self.user_id)

        ttl = self.redis.ttl(self.resend_key)

        self.assertGreater(ttl, 0)
        self.assertLessEqual(ttl, block.OTP_RESEND_COOLDOWN)

    def test_resend_is_not_allowed_during_cooldown(self):
        block.start_resend_cooldown(self.user_id)

        self.assertFalse(block.can_resend_verification_code(self.user_id))

    def test_locked_account_cannot_start_resend_cooldown(self):
        for _ in range(block.OTP_MAX_ATTEMPTS):
            block.increment_failed_attempts(self.user_id)

        result = block.start_resend_cooldown(self.user_id)

        self.assertFalse(result)
        self.assertFalse(self.redis.exists(self.resend_key))
