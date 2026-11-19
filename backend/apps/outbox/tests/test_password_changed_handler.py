from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase

from apps.outbox.handlers.password_changed import (
    handle_password_changed,
)


class PasswordChangedHandlerTests(SimpleTestCase):
    def setUp(self):
        self.user_id = uuid4()
        self.email = "user@example.com"

        self.payload = {
            "email": self.email,
        }

    @patch(
        "apps.outbox.handlers.password_changed."
        "send_password_changed_email.delay"
    )
    def test_successful_handling(self, mock_send_email):
        handle_password_changed(
            self.user_id,
            self.payload,
        )

        mock_send_email.assert_called_once_with(
            email=self.email,
        )

    @patch(
        "apps.outbox.handlers.password_changed."
        "send_password_changed_email.delay"
    )
    def test_handler_does_not_modify_payload(
        self,
        mock_send_email,
    ):
        original_payload = self.payload.copy()

        handle_password_changed(
            self.user_id,
            self.payload,
        )

        self.assertEqual(self.payload, original_payload)
        mock_send_email.assert_called_once_with(
            email=self.email,
        )
