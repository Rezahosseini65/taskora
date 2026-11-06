
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


class UserLoginViewTests(APITestCase):

    def setUp(self):
        self.url = reverse("users:user-login")
        self.password = "StrongPassword123"

        self.user = User.objects.create_user(
            email="user@example.com",
            password=self.password,
            status=User.AccountStatus.ACTIVE,
        )

    def test_successful_login(self):
        response = self.client.post(
            self.url,
            {
                "email": "user@example.com",
                "password": self.password,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["detail"],
            "Login successful",
        )

        self.assertNotIn("access", response.data)
        self.assertNotIn("refresh", response.data)

        self.assertIn("access_token", response.cookies)
        self.assertIn("refresh_token", response.cookies)

        self.assertTrue(
            response.cookies["access_token"]["httponly"]
        )
        self.assertTrue(
            response.cookies["refresh_token"]["httponly"]
        )

    def test_login_with_incorrect_password(self):
        response = self.client.post(
            self.url,
            {
                "email": "user@example.com",
                "password": "WrongPassword123",
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertNotIn("access_token", response.cookies)
        self.assertNotIn("refresh_token", response.cookies)

    def test_login_with_suspended_account(self):
        self.user.status = User.AccountStatus.SUSPENDED
        self.user.save(update_fields=["status"])

        response = self.client.post(
            self.url,
            {
                "email": "user@example.com",
                "password": self.password,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertNotIn("access_token", response.cookies)

    def test_login_with_deactivated_account(self):
        self.user.status = User.AccountStatus.DEACTIVATED
        self.user.save(update_fields=["status"])

        response = self.client.post(
            self.url,
            {
                "email": "user@example.com",
                "password": self.password,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertNotIn("access_token", response.cookies)

    def test_login_with_inactive_user(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        response = self.client.post(
            self.url,
            {
                "email": "user@example.com",
                "password": self.password,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertNotIn("access_token", response.cookies)

    def test_login_with_nonexistent_email(self):
        response = self.client.post(
            self.url,
            {
                "email": "unknown@example.com",
                "password": self.password,
            },
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertNotIn("access_token", response.cookies)


class CSRFTokenViewTests(APITestCase):

    def test_csrf_endpoint_returns_success_and_sets_cookie(self):
        response = self.client.get(
            reverse("users:csrf-token")
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(
            "csrftoken",
            response.cookies,
        )
        self.assertTrue(response.cookies["csrftoken"].value)