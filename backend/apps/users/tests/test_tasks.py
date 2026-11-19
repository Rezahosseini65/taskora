from unittest.mock import patch

from django.test import SimpleTestCase

from apps.users.tasks import send_verification_email


class SendVerificationEmailTaskTests(SimpleTestCase):
    def setUp(self):
        self.email = "user@example.com"
        self.verification_code = "123456"
        self.user_id = "user-uuid"
        self.generation = 2

    @patch("apps.users.tasks.send_mail")
    @patch("apps.users.tasks.otp.is_verification_code_current")
    def test_sends_email_for_current_generation(
        self,
        mock_is_current,
        mock_send_mail,
    ):
        mock_is_current.return_value = True

        result = send_verification_email(
            email=self.email,
            verification_code=self.verification_code,
            user_id=self.user_id,
            generation=self.generation,
        )

        self.assertIs(result, True)

        mock_is_current.assert_called_once_with(
            user_id=self.user_id,
            code=self.verification_code,
            generation=self.generation,
        )

        mock_send_mail.assert_called_once()

        call_kwargs = mock_send_mail.call_args.kwargs
        self.assertEqual(call_kwargs["recipient_list"], [self.email])
        self.assertIn(self.verification_code, call_kwargs["message"])
        self.assertIn("2 minutes", call_kwargs["message"])

    @patch("apps.users.tasks.send_mail")
    @patch("apps.users.tasks.otp.is_verification_code_current")
    def test_skips_email_for_outdated_generation(
        self,
        mock_is_current,
        mock_send_mail,
    ):
        mock_is_current.return_value = False

        result = send_verification_email(
            email=self.email,
            verification_code=self.verification_code,
            user_id=self.user_id,
            generation=self.generation,
        )

        self.assertIs(result, False)

        mock_is_current.assert_called_once_with(
            user_id=self.user_id,
            code=self.verification_code,
            generation=self.generation,
        )

        mock_send_mail.assert_not_called()

    @patch("apps.users.tasks.send_mail")
    @patch("apps.users.tasks.otp.is_verification_code_current")
    def test_skips_email_when_otp_does_not_exist(
        self,
        mock_is_current,
        mock_send_mail,
    ):
        mock_is_current.return_value = False

        result = send_verification_email(
            email=self.email,
            verification_code=self.verification_code,
            user_id=self.user_id,
            generation=self.generation,
        )

        self.assertIs(result, False)
        mock_send_mail.assert_not_called()

    @patch("apps.users.tasks.otp.is_verification_code_current")
    @patch(
        "apps.users.tasks.send_mail",
        side_effect=RuntimeError("SMTP unavailable"),
    )
    def test_retries_when_email_sending_fails(
        self,
        mock_send_mail,
        mock_is_current,
    ):
        mock_is_current.return_value = True

        with patch.object(
            send_verification_email,
            "retry",
            side_effect=RuntimeError("Retry requested"),
        ) as mock_retry:
            with self.assertRaisesMessage(
                RuntimeError,
                "Retry requested",
            ):
                send_verification_email(
                    email=self.email,
                    verification_code=self.verification_code,
                    user_id=self.user_id,
                    generation=self.generation,
                )

        mock_is_current.assert_called_once()
        mock_send_mail.assert_called_once()
        mock_retry.assert_called_once()
