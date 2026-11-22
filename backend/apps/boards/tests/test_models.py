from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.organizations.models import Organization
from apps.workspaces.models import Workspace
from apps.boards.models import Board

User = get_user_model()


class BoardModelTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com",
            password="test-password-123",
        )
        self.organization = Organization.objects.create(
            name="Taskora",
            created_by=self.owner,
        )
        self.workspace = Workspace.objects.create(
            organization=self.organization,
            name="Development",
            created_by=self.owner,
        )

    def create_board(self, **kwargs):
        defaults = {
            "workspace": self.workspace,
            "name": "Backend",
            "created_by": self.owner,
        }
        defaults.update(kwargs)
        return Board.objects.create(**defaults)

    def test_create_board(self):
        board = self.create_board()

        self.assertEqual(board.name, "Backend")
        self.assertEqual(board.workspace, self.workspace)
        self.assertEqual(board.created_by, self.owner)
        self.assertEqual(board.settings, {})
        self.assertFalse(board.is_archived)
        self.assertIsNotNone(board.id)

    def test_name_is_stripped_on_save(self):
        board = self.create_board(name="  Backend  ")

        self.assertEqual(board.name, "Backend")

    def test_name_is_unique_case_insensitively_per_workspace(self):
        self.create_board(name="backend")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_board(name="Backend")

    def test_same_name_is_allowed_in_different_workspaces(self):
        second_workspace = Workspace.objects.create(
            organization=self.organization,
            name="Frontend",
            created_by=self.owner,
        )

        first = self.create_board(name="Development")
        second = self.create_board(
            workspace=second_workspace,
            name="Development",
        )

        self.assertNotEqual(first.pk, second.pk)

    def test_slug_is_generated_when_empty(self):
        board = self.create_board(name="Backend Development")

        self.assertEqual(board.slug, "backend-development")

    def test_custom_slug_is_preserved(self):
        board = self.create_board(slug="custom-board")

        self.assertEqual(board.slug, "custom-board")

    def test_duplicate_slug_is_rejected_per_workspace(self):
        self.create_board(slug="backend")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_board(
                    name="Another Board",
                    slug="backend",
                )

    def test_same_slug_is_allowed_in_different_workspaces(self):
        second_workspace = Workspace.objects.create(
            organization=self.organization,
            name="Frontend",
            created_by=self.owner,
        )

        first = self.create_board(
            workspace=self.workspace,
            slug="development",
        )
        second = self.create_board(
            workspace=second_workspace,
            name="Development",
            slug="development",
        )

        self.assertNotEqual(first.pk, second.pk)

    def test_objects_excludes_soft_deleted_boards(self):
        board = self.create_board()
        board.soft_delete()

        self.assertFalse(
            Board.objects.filter(pk=board.pk).exists()
        )
        self.assertTrue(
            Board.all_objects.filter(pk=board.pk).exists()
        )

    def test_soft_delete(self):
        board = self.create_board()

        board.soft_delete()
        board.refresh_from_db()

        self.assertIsNotNone(board.deleted_at)

    def test_soft_delete_is_idempotent(self):
        board = self.create_board()
        board.soft_delete()
        deleted_at = board.deleted_at

        board.soft_delete()
        board.refresh_from_db()

        self.assertEqual(board.deleted_at, deleted_at)

    def test_restore(self):
        board = self.create_board()
        board.soft_delete()
        board.restore()
        board.refresh_from_db()

        self.assertIsNone(board.deleted_at)
        self.assertTrue(
            Board.objects.filter(pk=board.pk).exists()
        )

    def test_deleted_board_name_remains_reserved(self):
        self.create_board(name="Backend").soft_delete()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_board(name="BACKEND")

    def test_deleted_board_slug_remains_reserved(self):
        self.create_board(slug="backend").soft_delete()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_board(
                    name="Another Board",
                    slug="backend",
                )

    def test_archived_board_is_not_soft_deleted(self):
        board = self.create_board(is_archived=True)

        self.assertTrue(board.is_archived)
        self.assertIsNone(board.deleted_at)
        self.assertTrue(
            Board.objects.filter(pk=board.pk).exists()
        )

    def test_unarchived_board_remains_active(self):
        board = self.create_board(is_archived=True)

        board.is_archived = False
        board.save(update_fields=["is_archived", "updated_at"])

        board.refresh_from_db()

        self.assertFalse(board.is_archived)
        self.assertIsNone(board.deleted_at)
