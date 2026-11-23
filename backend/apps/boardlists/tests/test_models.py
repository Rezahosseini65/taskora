from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.boardlists.models import BoardList
from apps.boards.services import create_board
from apps.organizations.services import create_organization
from apps.users.models import User
from apps.workspaces.services import create_workspace


class BoardListModelTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            email="boardlist-owner@example.com",
            password="TestPassword123!",
        )

        cls.organization = create_organization(
            name="BoardList Organization",
            created_by=cls.owner,
        )

        cls.workspace = create_workspace(
            organization=cls.organization,
            name="BoardList Workspace",
            created_by=cls.owner,
        )

        cls.board = create_board(
            workspace=cls.workspace,
            name="BoardList Board",
            created_by=cls.owner,
        )

        cls.second_board = create_board(
            workspace=cls.workspace,
            name="Second Board",
            created_by=cls.owner,
        )

    def create_list(self, *, board=None, name="Review", position=4, **kwargs):
        return BoardList.objects.create(
            board=board or self.board,
            name=name,
            position=position,
            **kwargs,
        )


class BoardListCreationTests(BoardListModelTestCase):
    def test_create_board_list(self):
        board_list = self.create_list()

        self.assertEqual(board_list.board, self.board)
        self.assertEqual(board_list.name, "Review")
        self.assertEqual(board_list.position, 4)
        self.assertFalse(board_list.is_archived)
        self.assertIsNone(board_list.deleted_at)

    def test_name_is_stripped_on_save(self):
        board_list = self.create_list(name="  Review  ")

        self.assertEqual(board_list.name, "Review")

    def test_empty_name_is_not_valid(self):
        board_list = BoardList(
            board=self.board,
            name="   ",
            position=4,
        )

        with self.assertRaises(ValidationError):
            board_list.full_clean()

    def test_same_name_is_allowed_in_different_boards(self):
        first_list = self.create_list(
            board=self.board,
            name="Review",
            position=4,
        )

        second_list = self.create_list(
            board=self.second_board,
            name="Review",
            position=4,
        )

        self.assertEqual(first_list.name, second_list.name)
        self.assertNotEqual(first_list.pk, second_list.pk)


class BoardListConstraintTests(BoardListModelTestCase):
    def test_name_must_be_unique_case_insensitively(self):
        self.create_list(name="Review", position=4)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_list(name="review", position=5)

    def test_position_must_be_unique_per_board(self):
        self.create_list(name="Review", position=4)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_list(name="Another", position=4)

    def test_deleted_list_name_remains_reserved(self):
        board_list = self.create_list(
            name="Review",
            position=4,
        )
        board_list.soft_delete()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_list(
                    name="review",
                    position=5,
                )

    def test_deleted_list_position_remains_reserved(self):
        board_list = self.create_list(
            name="Review",
            position=4,
        )
        board_list.soft_delete()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_list(
                    name="Another",
                    position=4,
                )


class BoardListManagerTests(BoardListModelTestCase):
    def test_default_manager_excludes_deleted_lists(self):
        board_list = self.create_list()
        board_list.soft_delete()

        self.assertFalse(
            BoardList.objects.filter(pk=board_list.pk).exists()
        )

    def test_all_objects_manager_includes_deleted_lists(self):
        board_list = self.create_list()
        board_list.soft_delete()

        self.assertTrue(
            BoardList.all_objects.filter(pk=board_list.pk).exists()
        )

    def test_default_manager_includes_active_lists(self):
        board_list = self.create_list()

        self.assertTrue(
            BoardList.objects.filter(pk=board_list.pk).exists()
        )


class BoardListLifecycleTests(BoardListModelTestCase):
    def test_soft_delete(self):
        board_list = self.create_list()

        board_list.soft_delete()

        board_list.refresh_from_db()

        self.assertIsNotNone(board_list.deleted_at)
        self.assertFalse(
            BoardList.objects.filter(pk=board_list.pk).exists()
        )

    def test_soft_delete_is_idempotent(self):
        board_list = self.create_list()

        board_list.soft_delete()
        first_deleted_at = board_list.deleted_at

        board_list.soft_delete()
        board_list.refresh_from_db()

        self.assertEqual(board_list.deleted_at, first_deleted_at)

    def test_restore(self):
        board_list = self.create_list()

        board_list.soft_delete()
        board_list.restore()
        board_list.refresh_from_db()

        self.assertIsNone(board_list.deleted_at)
        self.assertTrue(
            BoardList.objects.filter(pk=board_list.pk).exists()
        )

    def test_restore_preserves_position(self):
        board_list = self.create_list(position=4)

        board_list.soft_delete()
        board_list.restore()
        board_list.refresh_from_db()

        self.assertEqual(board_list.position, 4)

    def test_archive_is_independent_from_soft_delete(self):
        board_list = self.create_list()

        board_list.is_archived = True
        board_list.save(update_fields=["is_archived", "updated_at"])

        board_list.soft_delete()
        board_list.refresh_from_db()

        self.assertTrue(board_list.is_archived)
        self.assertIsNotNone(board_list.deleted_at)

    def test_unarchived_list_remains_active(self):
        board_list = self.create_list()

        board_list.is_archived = True
        board_list.save(update_fields=["is_archived", "updated_at"])

        board_list.is_archived = False
        board_list.save(update_fields=["is_archived", "updated_at"])

        board_list.refresh_from_db()

        self.assertFalse(board_list.is_archived)
        self.assertIsNone(board_list.deleted_at)
        self.assertTrue(
            BoardList.objects.filter(pk=board_list.pk).exists()
        )
