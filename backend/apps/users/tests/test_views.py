
from unittest.mock import patch

from django.urls import reverse

from rest_framework import status
from rest_framework.test import APITestCase

from apps.users.models import User


class UserRegisterViewTests(APITestCase):

    def setUp(self):
        self.url = reverse("users:user-register")

        self.valid_data = {
            "email": "newuser@example.com",
            "password": "StrongPassword123",
            "confirm_password": "StrongPassword123",
        }

    def test_successful_registration(self):
        response = self.client.post(
            self.url,
            self.valid_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.data,
            {"detail": "Registration successful"},
        )

        user = User.objects.get(email="newuser@example.com")
        self.assertTrue(user.check_password("StrongPassword123"))

        self.assertIn("access_token", response.cookies)
        self.assertIn("refresh_token", response.cookies)

        self.assertTrue(response.cookies["access_token"]["httponly"])
        self.assertTrue(response.cookies["refresh_token"]["httponly"])

    def test_registration_with_duplicate_email(self):
        User.objects.create_user(
            email="newuser@example.com",
            password="AnotherStrong123",
        )

        response = self.client.post(
            self.url,
            self.valid_data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data)

    def test_registration_with_invalid_email(self):
        data = {
            **self.valid_data,
            "email": "invalid-email",
        }

        response = self.client.post(
            self.url,
            data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data)

    def test_registration_with_password_mismatch(self):
        data = {
            **self.valid_data,
            "confirm_password": "DifferentPassword123",
        }

        response = self.client.post(
            self.url,
            data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("confirm_password", response.data)

    def test_registration_with_weak_password(self):
        data = {
            **self.valid_data,
            "password": "weakpassword",
            "confirm_password": "weakpassword",
        }

        response = self.client.post(
            self.url,
            data,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("password", response.data)

    @patch(
        "apps.users.views.generate_access_refresh_tokens",
        side_effect=RuntimeError("Token generation failed"),
    )
    def test_user_creation_is_rolled_back_if_token_generation_fails(
        self,
        mocked_token_generation,
    ):
        with self.assertRaises(RuntimeError):
            self.client.post(
                self.url,
                self.valid_data,
                format="json",
            )

        self.assertFalse(
            User.objects.filter(email="newuser@example.com").exists()
        )
        mocked_token_generation.assert_called_once()
