
from django.test import TestCase

from apps.users.models import User
from apps.users.serializers import (
    UserRegisterSerializer,
    UserLoginSerializer,
)


class UserRegisterSerializerTests(TestCase):

    def setUp(self):
        self.valid_data = {
            "email": "newuser@example.com",
            "password": "StrongPassword123",
            "confirm_password": "StrongPassword123",
        }

    def test_valid_registration_data(self):
        serializer = UserRegisterSerializer(data=self.valid_data)

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(
            serializer.validated_data["email"],
            "newuser@example.com",
        )

    def test_email_is_normalized(self):
        data = {
            **self.valid_data,
            "email": "  NewUser@Example.COM  ",
        }

        serializer = UserRegisterSerializer(data=data)

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(
            serializer.validated_data["email"],
            "newuser@example.com",
        )

    def test_duplicate_email_is_rejected(self):
        User.objects.create_user(
            email="newuser@example.com",
            password="AnotherStrong123",
        )

        serializer = UserRegisterSerializer(data=self.valid_data)

        self.assertFalse(serializer.is_valid())
        self.assertIn("email", serializer.errors)

    def test_soft_deleted_email_is_rejected(self):
        user = User.objects.create_user(
            email="newuser@example.com",
            password="AnotherStrong123",
        )
        user.soft_delete()

        serializer = UserRegisterSerializer(data=self.valid_data)

        self.assertFalse(serializer.is_valid())
        self.assertIn("email", serializer.errors)

    def test_password_confirmation_mismatch(self):
        data = {
            **self.valid_data,
            "confirm_password": "DifferentPassword123",
        }

        serializer = UserRegisterSerializer(data=data)

        self.assertFalse(serializer.is_valid())
        self.assertIn("confirm_password", serializer.errors)

    def test_password_without_uppercase_is_rejected(self):
        data = {
            **self.valid_data,
            "password": "strongpassword123",
            "confirm_password": "strongpassword123",
        }

        serializer = UserRegisterSerializer(data=data)

        self.assertFalse(serializer.is_valid())
        self.assertIn("password", serializer.errors)

    def test_password_similarity_to_email_is_rejected(self):
        data = {
            **self.valid_data,
            "password": "newuser@example.com",
            "confirm_password": "newuser@example.com",
        }

        serializer = UserRegisterSerializer(data=data)

        self.assertFalse(serializer.is_valid())
        self.assertIn("password", serializer.errors)


class UserLoginSerializerTests(TestCase):

    def setUp(self):
        self.password = "StrongPassword123"

        self.user = User.objects.create_user(
            email="user@example.com",
            password=self.password,
            status=User.AccountStatus.ACTIVE,
        )

    def test_valid_login(self):
        serializer = UserLoginSerializer(
            data={
                "email": "user@example.com",
                "password": self.password,
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["user"], self.user)

    def test_login_with_uppercase_email(self):
        serializer = UserLoginSerializer(
            data={
                "email": "USER@EXAMPLE.COM",
                "password": self.password,
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["user"], self.user)

    def test_login_with_incorrect_password(self):
        serializer = UserLoginSerializer(
            data={
                "email": "user@example.com",
                "password": "WrongPassword123",
            }
        )

        self.assertFalse(serializer.is_valid())

    def test_login_with_nonexistent_email(self):
        serializer = UserLoginSerializer(
            data={
                "email": "unknown@example.com",
                "password": self.password,
            }
        )

        self.assertFalse(serializer.is_valid())

    def test_login_with_pending_verification_account(self):
        self.user.status = User.AccountStatus.PENDING_VERIFICATION
        self.user.save(update_fields=["status"])

        serializer = UserLoginSerializer(
            data={
                "email": "user@example.com",
                "password": self.password,
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_login_with_suspended_account(self):
        self.user.status = User.AccountStatus.SUSPENDED
        self.user.save(update_fields=["status"])

        serializer = UserLoginSerializer(
            data={
                "email": "user@example.com",
                "password": self.password,
            }
        )

        self.assertFalse(serializer.is_valid())

    def test_login_with_deactivated_account(self):
        self.user.status = User.AccountStatus.DEACTIVATED
        self.user.save(update_fields=["status"])

        serializer = UserLoginSerializer(
            data={
                "email": "user@example.com",
                "password": self.password,
            }
        )

        self.assertFalse(serializer.is_valid())

    def test_login_with_inactive_user(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        serializer = UserLoginSerializer(
            data={
                "email": "user@example.com",
                "password": self.password,
            }
        )

        self.assertFalse(serializer.is_valid())

    def test_login_with_soft_deleted_user(self):
        self.user.soft_delete()

        serializer = UserLoginSerializer(
            data={
                "email": "user@example.com",
                "password": self.password,
            }
        )

        self.assertFalse(serializer.is_valid())
