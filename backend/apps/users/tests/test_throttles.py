
from unittest.mock import patch

from django.core.cache import cache
from django.urls import reverse

from rest_framework import status
from rest_framework.response import Response
from rest_framework.test import APITestCase

from apps.users.throttles import (
    UserRegisterThrottle,
    UserLoginThrottle,
    EmailVerificationThrottle,
    EmailVerificationResendThrottle,
)


@patch.object(
    UserRegisterThrottle,
    "THROTTLE_RATES",
    {"user_register_throttle": "2/minute"},
)
class UserRegisterThrottleTests(APITestCase):

    def setUp(self):
        cache.clear()
        self.url = reverse("users:user-register")

    def get_valid_data(self, email):
        return {
            "email": email,
            "password": "StrongPassword123",
            "confirm_password": "StrongPassword123",
        }

    def test_registration_requests_are_throttled(self):
        for index in range(2):
            response = self.client.post(
                self.url,
                self.get_valid_data(f"user{index}@example.com"),
                format="json",
                REMOTE_ADDR="192.0.2.10",
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        response = self.client.post(
            self.url,
            self.get_valid_data("user3@example.com"),
            format="json",
            REMOTE_ADDR="192.0.2.10",
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_429_TOO_MANY_REQUESTS,
        )

    def test_different_ips_have_separate_throttle_limits(self):
        response1 = self.client.post(
            self.url,
            self.get_valid_data("user1@example.com"),
            format="json",
            REMOTE_ADDR="192.0.2.10",
        )
        response2 = self.client.post(
            self.url,
            self.get_valid_data("user2@example.com"),
            format="json",
            REMOTE_ADDR="192.0.2.11",
        )

        self.assertEqual(response1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response2.status_code, status.HTTP_201_CREATED)


@patch.object(
    UserLoginThrottle,
    "THROTTLE_RATES",
    {"user_login_throttle": "2/minute"},
)
class UserLoginThrottleTests(APITestCase):

    def setUp(self):
        cache.clear()
        self.url = reverse("users:user-login")
        self.credentials = {
            "email": "user@example.com",
            "password": "WrongPassword123",
        }

    def test_login_requests_are_throttled_per_ip(self):
        self.client.defaults["REMOTE_ADDR"] = "192.168.1.10"

        for _ in range(2):
            response = self.client.post(
                self.url,
                self.credentials,
                format="json",
            )
            self.assertEqual(
                response.status_code,
                status.HTTP_400_BAD_REQUEST,
            )

        response = self.client.post(
            self.url,
            self.credentials,
            format="json",
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_429_TOO_MANY_REQUESTS,
        )

    def test_different_ips_have_independent_throttle_limits(self):
        self.client.defaults["REMOTE_ADDR"] = "192.168.1.10"

        for _ in range(2):
            self.client.post(
                self.url,
                self.credentials,
                format="json",
            )

        response = self.client.post(
            self.url,
            self.credentials,
            format="json",
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_429_TOO_MANY_REQUESTS,
        )

        self.client.defaults["REMOTE_ADDR"] = "192.168.1.11"

        response = self.client.post(
            self.url,
            self.credentials,
            format="json",
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )


@patch.object(
    EmailVerificationThrottle,
    "THROTTLE_RATES",
    {"email_verification": "2/minute"},
)
class EmailVerificationThrottleTests(APITestCase):

    def setUp(self):
        cache.clear()
        self.url = reverse("users:email-verify")
        self.data = {
            "verification_token": "test-token",
            "verification_code": "123456",
        }

    @patch(
        "apps.users.views.EmailVerificationView.post",
        autospec=True,
        return_value=Response({"detail": "OK"}, status=status.HTTP_200_OK),
    )
    def test_verification_requests_are_throttled_per_ip(self, mock_post):
        # APIView dispatch applies throttling before calling post.
        self.client.defaults["REMOTE_ADDR"] = "192.0.2.20"

        for _ in range(2):
            response = self.client.post(
                self.url,
                self.data,
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.post(
            self.url,
            self.data,
            format="json",
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_429_TOO_MANY_REQUESTS,
        )

    @patch(
        "apps.users.views.EmailVerificationView.post",
        autospec=True,
        return_value=Response({"detail": "OK"}, status=status.HTTP_200_OK),
    )
    def test_different_ips_have_independent_throttle_limits(self, mock_post):
        response1 = self.client.post(
            self.url,
            self.data,
            format="json",
            REMOTE_ADDR="192.0.2.20",
        )
        response2 = self.client.post(
            self.url,
            self.data,
            format="json",
            REMOTE_ADDR="192.0.2.21",
        )

        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        self.assertEqual(response2.status_code, status.HTTP_200_OK)


@patch.object(
    EmailVerificationResendThrottle,
    "THROTTLE_RATES",
    {"email_verification_resend": "2/minute"},
)
class EmailVerificationResendThrottleTests(APITestCase):

    def setUp(self):
        cache.clear()
        self.url = reverse("users:email-resend")
        self.data = {
            "verification_token": "test-token",
        }

    @patch(
        "apps.users.views.ResendVerificationEmailView.post",
        autospec=True,
        return_value=Response(
            {"detail": "If the account is eligible, a verification email will be sent."},
            status=status.HTTP_200_OK,
        ),
    )
    def test_resend_requests_are_throttled_per_ip(self, mock_post):
        self.client.defaults["REMOTE_ADDR"] = "192.0.2.30"

        for _ in range(2):
            response = self.client.post(
                self.url,
                self.data,
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.post(
            self.url,
            self.data,
            format="json",
        )
        self.assertEqual(
            response.status_code,
            status.HTTP_429_TOO_MANY_REQUESTS,
        )

    @patch(
        "apps.users.views.ResendVerificationEmailView.post",
        autospec=True,
        return_value=Response(
            {"detail": "If the account is eligible, a verification email will be sent."},
            status=status.HTTP_200_OK,
        ),
    )
    def test_different_ips_have_independent_throttle_limits(self, mock_post):
        response1 = self.client.post(
            self.url,
            self.data,
            format="json",
            REMOTE_ADDR="192.0.2.30",
        )
        response2 = self.client.post(
            self.url,
            self.data,
            format="json",
            REMOTE_ADDR="192.0.2.31",
        )

        self.assertEqual(response1.status_code, status.HTTP_200_OK)
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
