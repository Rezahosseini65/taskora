
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase

from apps.outbox.handlers.email_verification import (
    handle_email_verification_requested,
)


class EmailVerificationHandlerTests(SimpleTestCase):
    def setUp(self):
        self.user_id = uuid4()
        self.email = "user@example.com"
        self.generation = 2
        self.verification_code = "123456"

        self.payload = {
            "email": self.email,
            "generation": self.generation,
        }

    @patch(
        "apps.outbox.handlers.email_verification.send_verification_email.delay"
    )
    @patch(
        "apps.outbox.handlers.email_verification.otp.store_verification_code"
    )
    @patch(
        "apps.outbox.handlers.email_verification.otp.generate_verification_code"
    )
    def test_successful_handling(
        self,
        mock_generate_code,
        mock_store_code,
        mock_send_email,
    ):
        mock_generate_code.return_value = self.verification_code
        mock_store_code.return_value = True

        handle_email_verification_requested(
            self.user_id,
            self.payload,
        )

        mock_generate_code.assert_called_once_with()

        mock_store_code.assert_called_once_with(
            user_id=self.user_id,
            code=self.verification_code,
            generation=self.generation,
        )

        mock_send_email.assert_called_once_with(
            email=self.email,
            verification_code=self.verification_code,
            user_id=str(self.user_id),
            generation=self.generation,
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
    def test_outdated_generation_does_not_send_email(
        self,
        mock_generate_code,
        mock_store_code,
        mock_send_email,
    ):
        mock_generate_code.return_value = self.verification_code
        mock_store_code.return_value = False

        handle_email_verification_requested(
            self.user_id,
            self.payload,
        )

        mock_store_code.assert_called_once_with(
            user_id=self.user_id,
            code=self.verification_code,
            generation=self.generation,
        )

        mock_send_email.assert_not_called()
