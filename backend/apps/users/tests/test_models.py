
import uuid

from django.test import TestCase

from apps.users.models import User


class UserModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="user@example.com",
            password="StrongPassword123",
        )

    def test_user_id_is_uuid(self):
        self.assertIsInstance(self.user.id, uuid.UUID)

    def test_user_default_values(self):
        self.assertEqual(
            self.user.status,
            User.AccountStatus.PENDING_VERIFICATION,
        )
        self.assertEqual(self.user.locale, "en")
        self.assertEqual(self.user.timezone, "UTC")
        self.assertTrue(self.user.is_active)
        self.assertFalse(self.user.is_staff)
        self.assertIsNone(self.user.email_verified_at)
        self.assertIsNone(self.user.deleted_at)

    def test_account_status_choices(self):
        expected_statuses = {
            "pending_verification",
            "active",
            "suspended",
            "deactivated",
        }
        actual_statuses = {
            value for value, label in User.AccountStatus.choices
        }
        self.assertEqual(actual_statuses, expected_statuses)

    def test_string_representation_returns_email(self):
        self.assertEqual(str(self.user), "user@example.com")

    def test_clean_normalizes_email(self):
        user = User(email="  USER@EXAMPLE.COM  ")
        user.clean()
        self.assertEqual(user.email, "user@example.com")

    def test_clean_does_not_modify_empty_email(self):
        user = User(email="")
        user.clean()
        self.assertEqual(user.email, "")

    def test_soft_delete_sets_deleted_at(self):
        self.assertIsNone(self.user.deleted_at)

        self.user.soft_delete()

        self.assertIsNotNone(self.user.deleted_at)
        self.assertIsNotNone(
            User.all_objects.get(pk=self.user.pk).deleted_at
        )

    def test_soft_delete_updates_updated_at(self):
        previous_updated_at = self.user.updated_at

        self.user.soft_delete()

        self.assertGreaterEqual(
            self.user.updated_at,
            previous_updated_at,
        )

    def test_soft_delete_is_idempotent(self):
        self.user.soft_delete()
        original_deleted_at = self.user.deleted_at
        original_updated_at = self.user.updated_at

        self.user.soft_delete()

        self.assertEqual(self.user.deleted_at, original_deleted_at)
        self.assertEqual(self.user.updated_at, original_updated_at)

    def test_restore_clears_deleted_at(self):
        self.user.soft_delete()

        self.user.restore()

        self.assertIsNone(self.user.deleted_at)
        self.assertIsNone(
            User.all_objects.get(pk=self.user.pk).deleted_at
        )

    def test_restore_updates_updated_at(self):
        self.user.soft_delete()
        previous_updated_at = self.user.updated_at

        self.user.restore()

        self.assertGreaterEqual(
            self.user.updated_at,
            previous_updated_at,
        )

    def test_restore_is_idempotent(self):
        original_updated_at = self.user.updated_at

        self.user.restore()

        self.assertIsNone(self.user.deleted_at)
        self.assertEqual(self.user.updated_at, original_updated_at)
