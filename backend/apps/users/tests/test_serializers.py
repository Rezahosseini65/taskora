from types import SimpleNamespace
from io import BytesIO

from PIL import Image

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.db import transaction

from apps.users.models import User, UserProfile
from apps.users.serializers import (
    UserRegisterSerializer,
    UserLoginSerializer,
    UserChangePasswordSerializer,
    UserMeSerializer,
)
from apps.users.services.verification import verify_verification_token


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
                "email": self.user.email,
                "password": self.password,
            },
        )

        self.assertFalse(serializer.is_valid())

        self.assertEqual(
            str(serializer.errors["code"][0]),
            "email_not_verified",
        )

        self.assertEqual(
            str(serializer.errors["detail"][0]),
            "Please verify your email address before logging in.",
        )

        self.assertEqual(
            str(serializer.errors["verification_required"][0]),
            "True",
        )

        verification_token = serializer.errors["verification_token"][0]

        self.assertIsNotNone(verification_token)

        token_user_id = verify_verification_token(
            str(verification_token)
        )

        self.assertEqual(token_user_id, self.user.id)

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


class UserChangePasswordSerializerTests(TestCase):
    def setUp(self):
        self.current_password = "CurrentStrong!2026"
        self.user = User.objects.create_user(
            email="password-change@example.com",
            password=self.current_password,
        )
        self.context = {
            "request": SimpleNamespace(user=self.user),
        }

    def get_serializer(self, **data):
        return UserChangePasswordSerializer(
            data=data,
            context=self.context,
        )

    def test_valid_password_change(self):
        serializer = self.get_serializer(
            current_password=self.current_password,
            new_password="NewStrongPassword!2026",
            confirm_new_password="NewStrongPassword!2026",
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_invalid_current_password(self):
        serializer = self.get_serializer(
            current_password="WrongPassword!2026",
            new_password="NewStrongPassword!2026",
            confirm_new_password="NewStrongPassword!2026",
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("current_password", serializer.errors)

    def test_password_confirmation_mismatch(self):
        serializer = self.get_serializer(
            current_password=self.current_password,
            new_password="NewStrongPassword!2026",
            confirm_new_password="DifferentPassword!2026",
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("confirm_new_password", serializer.errors)

    def test_weak_new_password(self):
        serializer = self.get_serializer(
            current_password=self.current_password,
            new_password="weak",
            confirm_new_password="weak",
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("new_password", serializer.errors)

    def test_new_password_same_as_current_password(self):
        serializer = self.get_serializer(
            current_password=self.current_password,
            new_password=self.current_password,
            confirm_new_password=self.current_password,
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("new_password", serializer.errors)

    def test_django_password_validators_are_applied(self):
        serializer = self.get_serializer(
            current_password=self.current_password,
            new_password="password123456",
            confirm_new_password="password123456",
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("new_password", serializer.errors)


class UserMeSerializerTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="profile@example.com",
            password="StrongPassword123",
        )

        self.profile = UserProfile.objects.create(
            user=self.user,
            first_name="Reza",
            last_name="Hosseini",
            display_name="Reza",
            bio="Initial bio",
            phone_number="09123456789",
        )

    def create_image(self, image_format="PNG", size=(32, 32)):
        image_file = BytesIO()
        image = Image.new("RGB", size, color="red")
        image.save(image_file, format=image_format)
        image_file.seek(0)

        extension = image_format.lower()

        return SimpleUploadedFile(
            f"avatar.{extension}",
            image_file.read(),
            content_type=f"image/{extension}",
        )

    def test_serializer_returns_user_and_profile_data(self):
        serializer = UserMeSerializer(instance=self.user)

        data = serializer.data

        self.assertEqual(data["email"], self.user.email)
        self.assertEqual(data["first_name"], "Reza")
        self.assertEqual(data["last_name"], "Hosseini")
        self.assertEqual(data["display_name"], "Reza")
        self.assertEqual(data["bio"], "Initial bio")
        self.assertEqual(data["phone_number"], "09123456789")

    def test_update_profile_fields(self):
        serializer = UserMeSerializer(
            instance=self.user,
            data={
                "first_name": "Ali",
                "last_name": "Ahmadi",
                "display_name": "Ali",
                "bio": "Updated bio",
                "phone_number": "09111111111",
            },
            partial=True,
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()

        self.profile.refresh_from_db()

        self.assertEqual(self.profile.first_name, "Ali")
        self.assertEqual(self.profile.last_name, "Ahmadi")
        self.assertEqual(self.profile.display_name, "Ali")
        self.assertEqual(self.profile.bio, "Updated bio")
        self.assertEqual(self.profile.phone_number, "09111111111")

    def test_update_user_fields(self):
        serializer = UserMeSerializer(
            instance=self.user,
            data={
                "locale": "fa",
                "timezone": "Asia/Tehran",
            },
            partial=True,
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()

        self.user.refresh_from_db()

        self.assertEqual(self.user.locale, "fa")
        self.assertEqual(self.user.timezone, "Asia/Tehran")

    def test_update_creates_profile_if_missing(self):
        self.profile.delete()

        serializer = UserMeSerializer(
            instance=self.user,
            data={"first_name": "New"},
            partial=True,
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()

        profile = UserProfile.objects.get(user=self.user)

        self.assertEqual(profile.first_name, "New")

    def test_read_only_fields_are_not_updated(self):
        original_email = self.user.email
        original_id = self.user.id

        serializer = UserMeSerializer(
            instance=self.user,
            data={
                "email": "changed@example.com",
                "id": "00000000-0000-0000-0000-000000000001",
            },
            partial=True,
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()

        self.user.refresh_from_db()

        self.assertEqual(self.user.email, original_email)
        self.assertEqual(self.user.id, original_id)

    def test_valid_png_avatar_is_accepted(self):
        avatar = self.create_image("PNG")

        serializer = UserMeSerializer(
            instance=self.user,
            data={"avatar": avatar},
            partial=True,
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_valid_jpeg_avatar_is_accepted(self):
        avatar = self.create_image("JPEG")

        serializer = UserMeSerializer(
            instance=self.user,
            data={"avatar": avatar},
            partial=True,
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_valid_webp_avatar_is_accepted(self):
        avatar = self.create_image("WEBP")

        serializer = UserMeSerializer(
            instance=self.user,
            data={"avatar": avatar},
            partial=True,
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_unsupported_avatar_format_is_rejected(self):
        avatar = self.create_image("GIF")

        serializer = UserMeSerializer(
            instance=self.user,
            data={"avatar": avatar},
            partial=True,
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("avatar", serializer.errors)

    def test_invalid_image_is_rejected(self):
        avatar = SimpleUploadedFile(
            "fake.png",
            b"this is not an image",
            content_type="image/png",
        )

        serializer = UserMeSerializer(
            instance=self.user,
            data={"avatar": avatar},
            partial=True,
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("avatar", serializer.errors)

    def test_avatar_larger_than_5mb_is_rejected(self):
        valid_image = self.create_image("PNG")
        content = valid_image.read()

        oversized_avatar = SimpleUploadedFile(
            "large.png",
            content + (b"x" * (5 * 1024 * 1024)),
            content_type="image/png",
        )

        serializer = UserMeSerializer(
            instance=self.user,
            data={"avatar": oversized_avatar},
            partial=True,
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("avatar", serializer.errors)

    def test_avatar_exceeding_max_dimensions_is_rejected(self):
        avatar = self.create_image("PNG", size=(4097, 100))

        serializer = UserMeSerializer(
            instance=self.user,
            data={"avatar": avatar},
            partial=True,
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("avatar", serializer.errors)

    def test_avatar_can_be_cleared(self):
        serializer = UserMeSerializer(
            instance=self.user,
            data={"avatar": None},
            partial=True,
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()

        self.profile.refresh_from_db()
        self.assertFalse(self.profile.avatar)

    def test_old_avatar_is_deleted_after_replacement(self):
        old_avatar = self.create_image("PNG")
        self.profile.avatar.save(
            "old.png",
            old_avatar,
            save=True,
        )
        old_avatar_name = self.profile.avatar.name
        storage = self.profile.avatar.storage

        new_avatar = self.create_image("JPEG")

        serializer = UserMeSerializer(
            instance=self.user,
            data={"avatar": new_avatar},
            partial=True,
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

        with self.captureOnCommitCallbacks(execute=True):
            serializer.save()

        self.assertFalse(storage.exists(old_avatar_name))

        self.profile.refresh_from_db()
        self.assertTrue(storage.exists(self.profile.avatar.name))
        self.assertNotEqual(self.profile.avatar.name, old_avatar_name)

    def test_old_avatar_is_deleted_after_clearing(self):
        old_avatar = self.create_image("PNG")
        self.profile.avatar.save(
            "old.png",
            old_avatar,
            save=True,
        )
        old_avatar_name = self.profile.avatar.name
        storage = self.profile.avatar.storage

        serializer = UserMeSerializer(
            instance=self.user,
            data={"avatar": None},
            partial=True,
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

        with self.captureOnCommitCallbacks(execute=True):
            serializer.save()

        self.assertFalse(storage.exists(old_avatar_name))

        self.profile.refresh_from_db()
        self.assertFalse(self.profile.avatar)

    def test_old_avatar_is_preserved_when_other_fields_are_updated(self):
        old_avatar = self.create_image("PNG")
        self.profile.avatar.save(
            "old.png",
            old_avatar,
            save=True,
        )
        old_avatar_name = self.profile.avatar.name
        storage = self.profile.avatar.storage

        serializer = UserMeSerializer(
            instance=self.user,
            data={"bio": "Updated bio"},
            partial=True,
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

        with self.captureOnCommitCallbacks(execute=True):
            serializer.save()

        self.profile.refresh_from_db()

        self.assertTrue(storage.exists(old_avatar_name))
        self.assertEqual(self.profile.avatar.name, old_avatar_name)
        self.assertEqual(self.profile.bio, "Updated bio")

    def test_old_avatar_is_preserved_when_transaction_rolls_back(self):
        old_avatar = self.create_image("PNG")
        self.profile.avatar.save(
            "old.png",
            old_avatar,
            save=True,
        )
        old_avatar_name = self.profile.avatar.name
        storage = self.profile.avatar.storage

        new_avatar = self.create_image("JPEG")

        serializer = UserMeSerializer(
            instance=self.user,
            data={"avatar": new_avatar},
            partial=True,
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

        with self.assertRaises(RuntimeError):
            with self.captureOnCommitCallbacks(execute=True):
                with transaction.atomic():
                    serializer.save()
                    raise RuntimeError("Simulated transaction rollback")

        self.assertTrue(storage.exists(old_avatar_name))

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.avatar.name, old_avatar_name)
