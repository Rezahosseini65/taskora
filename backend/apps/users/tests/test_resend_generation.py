
import uuid
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIRequestFactory

from apps.users.models import User
from apps.users.services import block, otp
from apps.users.views import ResendVerificationEmailView
from apps.outbox.handlers.email_verification import (
    handle_email_verification_requested,
)


class ResendGenerationRedisTests(TestCase):
    """
    Tests for Redis-based resend reservations and generation activation.
    """

    def setUp(self):
        self.user_id = uuid.uuid4()
        self.redis = block._get_redis_client()
        self.request_ids = []

        self.generation_key = block._get_generation_key(self.user_id)
        self.resend_key = block._get_resend_key(self.user_id)
        self.lock_key = block._get_lock_key(self.user_id)

        self.redis.delete(
            self.generation_key,
            self.resend_key,
            self.lock_key,
            block._get_attempts_key(self.user_id),
        )

    def tearDown(self):
        keys = [
            self.generation_key,
            self.resend_key,
            self.lock_key,
            block._get_attempts_key(self.user_id),
        ]

        for request_id in self.request_ids:
            keys.append(
                block._get_resend_generation_key(
                    self.user_id,
                    request_id,
                )
            )

        self.redis.delete(*keys)

    def reserve_resend(self):
        request_id = block.start_resend_cooldown(self.user_id)

        if request_id:
            self.request_ids.append(request_id)

        return request_id

    def test_initialize_generation_starts_at_one(self):
        generation = block.initialize_generation(self.user_id)

        self.assertEqual(generation, 1)
        self.assertEqual(
            self.redis.get(self.generation_key),
            b"1",
        )

    def test_initialize_generation_does_not_overwrite_existing_value(self):
        self.redis.set(self.generation_key, "4")

        generation = block.initialize_generation(self.user_id)

        self.assertEqual(generation, 4)

    def test_resend_reservation_does_not_increment_generation(self):
        block.initialize_generation(self.user_id)

        request_id = self.reserve_resend()

        self.assertIsNotNone(request_id)
        self.assertEqual(
            self.redis.get(self.generation_key),
            b"1",
        )
        self.assertEqual(
            self.redis.get(self.resend_key),
            request_id.encode(),
        )

    def test_second_reservation_is_rejected_during_cooldown(self):
        block.initialize_generation(self.user_id)

        first_request_id = self.reserve_resend()
        second_request_id = block.start_resend_cooldown(self.user_id)

        self.assertIsNotNone(first_request_id)
        self.assertIsNone(second_request_id)

    def test_locked_account_cannot_reserve_resend(self):
        block.initialize_generation(self.user_id)
        self.redis.set(
            self.lock_key,
            "1",
            ex=block.OTP_LOCK_DURATION,
        )

        request_id = block.start_resend_cooldown(self.user_id)

        self.assertIsNone(request_id)

    def test_activation_increments_generation_once(self):
        block.initialize_generation(self.user_id)
        request_id = self.reserve_resend()

        first_result = block.activate_resend_generation(
            self.user_id,
            request_id,
        )
        second_result = block.activate_resend_generation(
            self.user_id,
            request_id,
        )

        self.assertEqual(first_result, 2)
        self.assertEqual(second_result, 2)
        self.assertEqual(
            self.redis.get(self.generation_key),
            b"2",
        )

    def test_different_requests_increment_generation_separately(self):
        block.initialize_generation(self.user_id)

        first_request_id = self.reserve_resend()

        first_generation = block.activate_resend_generation(
            self.user_id,
            first_request_id,
        )

        block.clear_resend_cooldown(
            self.user_id,
            first_request_id,
        )

        second_request_id = self.reserve_resend()

        second_generation = block.activate_resend_generation(
            self.user_id,
            second_request_id,
        )

        self.assertEqual(first_generation, 2)
        self.assertEqual(second_generation, 3)
        self.assertEqual(
            self.redis.get(self.generation_key),
            b"3",
        )

    def test_activation_fails_when_generation_is_not_initialized(self):
        request_id = self.reserve_resend()

        with self.assertRaises(RuntimeError):
            block.activate_resend_generation(
                self.user_id,
                request_id,
            )

    def test_clear_cooldown_requires_matching_request_id(self):
        request_id = self.reserve_resend()

        result = block.clear_resend_cooldown(
            self.user_id,
            "another-request-id",
        )

        self.assertFalse(result)
        self.assertEqual(
            self.redis.get(self.resend_key),
            request_id.encode(),
        )

    def test_clear_cooldown_succeeds_for_matching_request_id(self):
        request_id = self.reserve_resend()

        result = block.clear_resend_cooldown(
            self.user_id,
            request_id,
        )

        self.assertTrue(result)
        self.assertIsNone(self.redis.get(self.resend_key))

    def test_clearing_cooldown_does_not_change_generation(self):
        block.initialize_generation(self.user_id)
        request_id = self.reserve_resend()

        block.clear_resend_cooldown(
            self.user_id,
            request_id,
        )

        self.assertEqual(
            self.redis.get(self.generation_key),
            b"1",
        )


class OTPConfigurationTests(TestCase):
    def test_otp_ttl_is_two_minutes(self):
        self.assertEqual(otp.OTP_TTL, 120)

    def test_otp_length_is_six_digits(self):
        self.assertEqual(otp.OTP_LENGTH, 6)

    def test_generated_otp_has_six_digits(self):
        code = otp.generate_verification_code()

        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())


class EmailVerificationHandlerTests(TestCase):
    """
    Tests for registration and resend Outbox event handling.
    """

    def setUp(self):
        self.user_id = uuid.uuid4()
        self.email = "user@example.com"

    @patch(
        "apps.outbox.handlers.email_verification.send_verification_email.delay"
    )
    @patch(
        "apps.outbox.handlers.email_verification.otp.store_verification_code"
    )
    @patch(
        "apps.outbox.handlers.email_verification.otp.generate_verification_code"
    )
    @patch(
        "apps.outbox.handlers.email_verification.block.activate_resend_generation"
    )
    def test_resend_handler_activates_generation_and_sends_email(
        self,
        mock_activate,
        mock_generate,
        mock_store,
        mock_send,
    ):
        mock_activate.return_value = 2
        mock_generate.return_value = "123456"
        mock_store.return_value = True

        handle_email_verification_requested(
            self.user_id,
            {
                "email": self.email,
                "request_id": "request-123",
            },
        )

        mock_activate.assert_called_once_with(
            user_id=self.user_id,
            request_id="request-123",
        )

        mock_store.assert_called_once_with(
            user_id=self.user_id,
            code="123456",
            generation=2,
        )

        mock_send.assert_called_once_with(
            email=self.email,
            verification_code="123456",
            user_id=str(self.user_id),
            generation=2,
        )

    @patch(
        "apps.outbox.handlers.email_verification.send_verification_email.delay"
    )
    @patch(
        "apps.outbox.handlers.email_verification.otp.store_verification_code"
    )
    @patch(
        "apps.outbox.handlers.email_verification.otp.generate_verification_code"
    )
    @patch(
        "apps.outbox.handlers.email_verification.block.activate_resend_generation"
    )
    def test_registration_handler_uses_initial_generation(
        self,
        mock_activate,
        mock_generate,
        mock_store,
        mock_send,
    ):
        mock_generate.return_value = "123456"
        mock_store.return_value = True

        handle_email_verification_requested(
            self.user_id,
            {
                "email": self.email,
                "generation": 1,
            },
        )

        mock_activate.assert_not_called()

        mock_store.assert_called_once_with(
            user_id=self.user_id,
            code="123456",
            generation=1,
        )

        mock_send.assert_called_once()

    @patch(
        "apps.outbox.handlers.email_verification.send_verification_email.delay"
    )
    @patch(
        "apps.outbox.handlers.email_verification.otp.store_verification_code"
    )
    @patch(
        "apps.outbox.handlers.email_verification.otp.generate_verification_code"
    )
    @patch(
        "apps.outbox.handlers.email_verification.block.activate_resend_generation"
    )
    def test_handler_does_not_send_email_when_otp_storage_fails(
        self,
        mock_activate,
        mock_generate,
        mock_store,
        mock_send,
    ):
        mock_activate.return_value = 2
        mock_generate.return_value = "123456"
        mock_store.return_value = False

        handle_email_verification_requested(
            self.user_id,
            {
                "email": self.email,
                "request_id": "request-123",
            },
        )

        mock_store.assert_called_once()
        mock_send.assert_not_called()


class ResendVerificationViewGenerationTests(TestCase):
    """
    Tests for Outbox creation and post-commit generation activation.
    """

    def setUp(self):
        self.factory = APIRequestFactory()

        self.user = User.objects.create_user(
            email="resend@example.com",
            password="StrongPassword123!",
        )

        self.user_id = self.user.id
        self.request_id = "test-resend-request-123"

        self.url = "/auth/email/resend/"

        self.payload = {
            "verification_token": "valid-verification-token",
        }

        from unittest.mock import patch

        throttle_patcher = patch.object(
            ResendVerificationEmailView,
            "throttle_classes",
            [],
        )
        throttle_patcher.start()
        self.addCleanup(throttle_patcher.stop)

    @patch(
        "apps.users.views._activate_resend_generation_after_commit"
    )
    @patch(
        "apps.users.views.block.start_resend_cooldown"
    )
    @patch(
        "apps.users.views.create_outbox_event"
    )
    @patch(
        "apps.users.views.verify_verification_token"
    )
    def test_successful_resend_creates_event_and_registers_callback(
        self,
        mock_verify_token,
        mock_create_event,
        mock_start_cooldown,
        mock_activate_after_commit,
    ):
        mock_verify_token.return_value = self.user_id
        mock_start_cooldown.return_value = self.request_id

        request = self.factory.post(
            self.url,
            self.payload,
            format="json",
        )

        with self.captureOnCommitCallbacks(execute=True):
            response = ResendVerificationEmailView.as_view()(request)

        self.assertEqual(response.status_code, 200)

        mock_create_event.assert_called_once_with(
            event_type="users.email_verification_requested",
            aggregate_type="user",
            aggregate_id=self.user.id,
            payload={
                "email": self.user.email,
                "request_id": self.request_id,
            },
        )

        mock_activate_after_commit.assert_called_once_with(
            self.user.id,
            self.request_id,
        )

    @patch(
        "apps.users.views.block.clear_resend_cooldown"
    )
    @patch(
        "apps.users.views.block.start_resend_cooldown"
    )
    @patch(
        "apps.users.views.create_outbox_event"
    )
    @patch(
        "apps.users.views.verify_verification_token"
    )
    def test_outbox_failure_clears_reservation(
        self,
        mock_verify_token,
        mock_create_event,
        mock_start_cooldown,
        mock_clear_cooldown,
    ):
        mock_verify_token.return_value = self.user_id
        mock_start_cooldown.return_value = self.request_id
        mock_create_event.side_effect = RuntimeError(
            "Outbox database error"
        )

        request = self.factory.post(
            self.url,
            self.payload,
            format="json",
        )

        with self.assertRaises(RuntimeError):
            ResendVerificationEmailView.as_view()(request)

        mock_clear_cooldown.assert_called_once_with(
            self.user_id,
            self.request_id,
        )

    @patch(
        "apps.users.views.verify_verification_token"
    )
    def test_invalid_verification_token_returns_generic_response(
        self,
        mock_verify_token,
    ):
        mock_verify_token.return_value = None

        request = self.factory.post(
            self.url,
            self.payload,
            format="json",
        )

        response = ResendVerificationEmailView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            {
                "detail": (
                    "If the account is eligible, "
                    "a verification email will be sent."
                )
            },
        )
