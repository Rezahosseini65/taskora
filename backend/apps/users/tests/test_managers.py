
from django.test import TestCase

from apps.users.models import User


class CustomUserManagerTests(TestCase):
    def test_create_user_successfully(self):
        user = User.objects.create_user(
            email="user@example.com",
            password="StrongPassword123",
        )

        self.assertEqual(user.email, "user@example.com")
        self.assertTrue(user.check_password("StrongPassword123"))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_create_user_normalizes_email(self):
        user = User.objects.create_user(
            email="  USER@EXAMPLE.COM  ",
            password="StrongPassword123",
        )

        self.assertEqual(user.email, "user@example.com")

    def test_create_user_without_password(self):
        user = User.objects.create_user(
            email="user@example.com",
        )

        self.assertFalse(user.has_usable_password())

    def test_create_user_without_email_raises_error(self):
        with self.assertRaisesMessage(
            ValueError,
            "The given email must be set.",
        ):
            User.objects.create_user(email=None)

    def test_create_user_with_empty_email_raises_error(self):
        with self.assertRaisesMessage(
            ValueError,
            "The given email must be set.",
        ):
            User.objects.create_user(email="   ")

    def test_create_superuser_successfully(self):
        user = User.objects.create_superuser(
            email="admin@example.com",
            password="StrongPassword123",
        )

        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.check_password("StrongPassword123"))

    def test_create_superuser_with_is_staff_false_raises_error(self):
        with self.assertRaisesMessage(
            ValueError,
            "Superuser must have is_staff=True.",
        ):
            User.objects.create_superuser(
                email="admin@example.com",
                password="StrongPassword123",
                is_staff=False,
            )

    def test_create_superuser_with_is_superuser_false_raises_error(self):
        with self.assertRaisesMessage(
            ValueError,
            "Superuser must have is_superuser=True.",
        ):
            User.objects.create_superuser(
                email="admin@example.com",
                password="StrongPassword123",
                is_superuser=False,
            )

    def test_default_manager_excludes_soft_deleted_users(self):
        user = User.objects.create_user(
            email="deleted@example.com",
            password="StrongPassword123",
        )
        user.soft_delete()

        self.assertFalse(
            User.objects.filter(pk=user.pk).exists()
        )

    def test_all_users_manager_includes_soft_deleted_users(self):
        user = User.objects.create_user(
            email="deleted@example.com",
            password="StrongPassword123",
        )
        user.soft_delete()

        self.assertTrue(
            User.all_objects.filter(pk=user.pk).exists()
        )


class UserQuerySetTests(TestCase):
    def setUp(self):
        self.alive_user = User.objects.create_user(
            email="alive@example.com",
            password="StrongPassword123",
        )
        self.deleted_user = User.objects.create_user(
            email="deleted@example.com",
            password="StrongPassword123",
        )
        self.deleted_user.soft_delete()

    def test_alive_returns_only_non_deleted_users(self):
        users = User.all_objects.alive()

        self.assertQuerySetEqual(
            users.order_by("email"),
            [self.alive_user],
        )

    def test_deleted_returns_only_soft_deleted_users(self):
        users = User.all_objects.deleted()

        self.assertQuerySetEqual(
            users.order_by("email"),
            [self.deleted_user],
        )

    def test_queryset_soft_delete_updates_only_alive_users(self):
        updated_count = User.all_objects.soft_delete()

        self.assertEqual(updated_count, 1)
        self.assertIsNotNone(
            User.all_objects.get(pk=self.alive_user.pk).deleted_at
        )

    def test_queryset_restore_updates_only_deleted_users(self):
        updated_count = User.all_objects.restore()

        self.assertEqual(updated_count, 1)
        self.assertIsNone(
            User.all_objects.get(pk=self.deleted_user.pk).deleted_at
        )
        self.assertIsNone(
            User.all_objects.get(pk=self.alive_user.pk).deleted_at
        )
