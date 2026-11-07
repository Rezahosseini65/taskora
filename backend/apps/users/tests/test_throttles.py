from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from django.core.cache import cache

from rest_framework import status
from rest_framework.test import APITestCase

from apps.users.throttles import (
    UserRegisterThrottle,
    UserLoginThrottle,
)


TEST_SETTINGS = {
    "DEFAULT_THROTTLE_RATES": {
        "user_register_throttle": "2/minute",
    },
}

TEST_CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "taskora-test-throttle",
    }
}


@override_settings(
    REST_FRAMEWORK=TEST_SETTINGS,
    CACHES=TEST_CACHES,
)
@patch.object(
    UserRegisterThrottle,
    "THROTTLE_RATES",
    {"user_register_throttle": "2/minute"},
)
class UserRegisterThrottleTests(APITestCase):

    def setUp(self):
        self.url = reverse("users:user-register")
        cache.clear()

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
            self.assertEqual(
                response.status_code,
                status.HTTP_201_CREATED,
            )

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

        self.assertEqual(
            response1.status_code,
            status.HTTP_201_CREATED,
        )
        self.assertEqual(
            response2.status_code,
            status.HTTP_201_CREATED,
        )


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
