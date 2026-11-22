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
            email="owner@example.com",
            password="test-password",
        )

        cls.organization = create_organization(
            name="Test Organization",
            created_by=cls.owner,
        )

        cls.workspace = create_workspace(
            organization=cls.organization,
            name="Test Workspace",
            created_by=cls.owner,
        )

        cls.board = create_board(
            workspace=cls.workspace,
            name="Development",
            created_by=cls.owner,
        )

        cls.second_board = create_board(
            workspace=cls.workspace,
            name="Marketing",
            created_by=cls.owner,
        )


class BoardListCreationTests(BoardListModelTestCase):
    def test_create_board_list(self):
        board_list = BoardList.objects.create(
            board=self.board,
            name="To Do",
            position=1,
        )

        self.assertEqual(board_list.board, self.board)
        self.assertEqual(board_list.name, "To Do")
        self.assertEqual(board_list.position, 1)
        self.assertEqual(board_list.description, "")
        self.assertEqual(board_list.settings, {})
        self.assertFalse(board_list.is_archived)
        self.assertIsNone(board_list.deleted_at)

    def test_name_is_stripped_on_save(self):
        board_list = BoardList.objects.create(
            board=self.board,
            name="  In Progress  ",
            position=1,
        )

        self.assertEqual(board_list.name, "In Progress")

    def test_empty_name_is_not_valid(self):
        board_list = BoardList(
            board=self.board,
            name="   ",
            position=1,
        )

        with self.assertRaises(ValidationError):
            board_list.full_clean()

    def test_same_name_is_allowed_in_different_boards(self):
        first_list = BoardList.objects.create(
            board=self.board,
            name="To Do",
            position=1,
        )

        second_list = BoardList.objects.create(
            board=self.second_board,
            name="To Do",
            position=1,
        )

        self.assertNotEqual(first_list.pk, second_list.pk)


class BoardListConstraintTests(BoardListModelTestCase):
    def test_name_must_be_unique_case_insensitively(self):
        BoardList.objects.create(
            board=self.board,
            name="To Do",
            position=1,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BoardList.objects.create(
                    board=self.board,
                    name="to do",
                    position=2,
                )

    def test_position_must_be_unique_per_board(self):
        BoardList.objects.create(
            board=self.board,
            name="To Do",
            position=1,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BoardList.objects.create(
                    board=self.board,
                    name="In Progress",
                    position=1,
                )

    def test_deleted_list_name_remains_reserved(self):
        board_list = BoardList.objects.create(
            board=self.board,
            name="To Do",
            position=1,
        )
        board_list.soft_delete()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BoardList.objects.create(
                    board=self.board,
                    name="To Do",
                    position=2,
                )

    def test_deleted_list_position_remains_reserved(self):
        board_list = BoardList.objects.create(
            board=self.board,
            name="To Do",
            position=1,
        )
        board_list.soft_delete()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BoardList.objects.create(
                    board=self.board,
                    name="In Progress",
                    position=1,
                )


class BoardListManagerTests(BoardListModelTestCase):
    def test_default_manager_excludes_deleted_lists(self):
        board_list = BoardList.objects.create(
            board=self.board,
            name="To Do",
            position=1,
        )
        board_list.soft_delete()

        self.assertFalse(
            BoardList.objects.filter(pk=board_list.pk).exists()
        )
        self.assertTrue(
            BoardList.all_objects.filter(pk=board_list.pk).exists()
        )


class BoardListLifecycleTests(BoardListModelTestCase):
    def test_soft_delete(self):
        board_list = BoardList.objects.create(
            board=self.board,
            name="To Do",
            position=1,
        )

        board_list.soft_delete()

        self.assertIsNotNone(board_list.deleted_at)
        self.assertFalse(
            BoardList.objects.filter(pk=board_list.pk).exists()
        )

    def test_soft_delete_is_idempotent(self):
        board_list = BoardList.objects.create(
            board=self.board,
            name="To Do",
            position=1,
        )

        board_list.soft_delete()
        first_deleted_at = board_list.deleted_at

        board_list.soft_delete()

        self.assertEqual(board_list.deleted_at, first_deleted_at)

    def test_restore(self):
        board_list = BoardList.objects.create(
            board=self.board,
            name="To Do",
            position=1,
        )
        board_list.soft_delete()

        board_list.restore()

        self.assertIsNone(board_list.deleted_at)
        self.assertTrue(
            BoardList.objects.filter(pk=board_list.pk).exists()
        )

    def test_archive_is_independent_from_soft_delete(self):
        board_list = BoardList.objects.create(
            board=self.board,
            name="To Do",
            position=1,
            is_archived=True,
        )

        self.assertTrue(board_list.is_archived)
        self.assertIsNone(board_list.deleted_at)

    def test_unarchived_list_remains_active(self):
        board_list = BoardList.objects.create(
            board=self.board,
            name="To Do",
            position=1,
            is_archived=False,
        )

        self.assertTrue(
            BoardList.objects.filter(pk=board_list.pk).exists()
        )
