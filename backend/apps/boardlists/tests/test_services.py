from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.boardlists.models import BoardList
from apps.boardlists.services import (
    create_board_list,
    update_board_list,
    reorder_board_lists,
    archive_board_list,
    unarchive_board_list,
    delete_board_list,
    restore_board_list,
)
from apps.boards.services import create_board
from apps.organizations.models import OrganizationMembership, OrganizationRole
from apps.organizations.services import create_organization
from apps.users.models import User
from apps.workspaces.models import WorkspaceMembership, WorkspaceRole
from apps.workspaces.services import create_workspace


class BoardListServiceTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            email="owner@example.com",
            password="test-password",
        )
        cls.admin = User.objects.create_user(
            email="admin@example.com",
            password="test-password",
        )
        cls.member = User.objects.create_user(
            email="member@example.com",
            password="test-password",
        )
        cls.non_member = User.objects.create_user(
            email="nonmember@example.com",
            password="test-password",
        )

        cls.organization = create_organization(
            name="Test Organization",
            created_by=cls.owner,
        )

        OrganizationMembership.objects.create(
            organization=cls.organization,
            user=cls.admin,
            role=OrganizationRole.ADMIN,
        )

        OrganizationMembership.objects.create(
            organization=cls.organization,
            user=cls.member,
            role=OrganizationRole.MEMBER,
        )

        cls.workspace = create_workspace(
            organization=cls.organization,
            name="Test Workspace",
            created_by=cls.owner,
        )

        WorkspaceMembership.objects.create(
            workspace=cls.workspace,
            user=cls.admin,
            role=WorkspaceRole.ADMIN,
        )

        WorkspaceMembership.objects.create(
            workspace=cls.workspace,
            user=cls.member,
            role=WorkspaceRole.MEMBER,
        )

        cls.board = create_board(
            workspace=cls.workspace,
            name="Development",
            created_by=cls.owner,
        )


class CreateBoardListTests(BoardListServiceTestCase):

    def test_owner_can_create_board_list(self):
        board_list = create_board_list(
            board=self.board,
            actor=self.owner,
            name="Testing",
        )

        self.assertEqual(board_list.board, self.board)
        self.assertEqual(board_list.name, "Testing")
        self.assertEqual(board_list.position, 4)
        self.assertEqual(board_list.description, "")
        self.assertEqual(board_list.settings, {})
        self.assertFalse(board_list.is_archived)
        self.assertIsNone(board_list.deleted_at)

    def test_admin_can_create_board_list(self):
        board_list = create_board_list(
            board=self.board,
            actor=self.admin,
            name="Review",
        )

        self.assertEqual(board_list.name, "Review")
        self.assertEqual(board_list.position, 4)

    def test_member_cannot_create_board_list(self):
        with self.assertRaises(ValidationError):
            create_board_list(
                board=self.board,
                actor=self.member,
                name="Testing",
            )

    def test_non_member_cannot_create_board_list(self):
        with self.assertRaises(ValidationError):
            create_board_list(
                board=self.board,
                actor=self.non_member,
                name="Testing",
            )

    def test_board_list_name_is_trimmed(self):
        board_list = create_board_list(
            board=self.board,
            actor=self.owner,
            name="  Testing  ",
        )

        self.assertEqual(board_list.name, "Testing")

    def test_empty_name_is_rejected(self):
        with self.assertRaises(ValidationError):
            create_board_list(
                board=self.board,
                actor=self.owner,
                name="   ",
            )

    def test_name_longer_than_160_characters_is_rejected(self):
        with self.assertRaises(ValidationError):
            create_board_list(
                board=self.board,
                actor=self.owner,
                name="A" * 161,
            )

    def test_next_position_includes_deleted_lists(self):
        deleted_list = BoardList.objects.create(
            board=self.board,
            name="Temporary",
            position=4,
        )
        deleted_list.soft_delete()

        board_list = create_board_list(
            board=self.board,
            actor=self.owner,
            name="Testing",
        )

        self.assertEqual(board_list.position, 5)

    def test_duplicate_name_is_rejected_case_insensitively(self):
        BoardList.objects.create(
            board=self.board,
            name="Testing",
            position=4,
        )

        with self.assertRaises(ValidationError):
            create_board_list(
                board=self.board,
                actor=self.owner,
                name="testing",
            )

    def test_cannot_create_list_in_archived_board(self):
        self.board.is_archived = True
        self.board.save(update_fields=["is_archived", "updated_at"])

        with self.assertRaises(ValidationError):
            create_board_list(
                board=self.board,
                actor=self.owner,
                name="Testing",
            )

    def test_created_list_is_saved_in_database(self):
        board_list = create_board_list(
            board=self.board,
            actor=self.owner,
            name="Testing",
        )

        self.assertTrue(
            BoardList.objects.filter(pk=board_list.pk).exists()
        )


class UpdateBoardListTests(BoardListServiceTestCase):

    def setUp(self):
        self.board_list = BoardList.objects.get(
            board=self.board,
            position=1,
        )

    def test_owner_can_update_board_list(self):
        updated = update_board_list(
            board_list=self.board_list,
            actor=self.owner,
            name="Backlog",
            description="Tasks waiting to be started.",
            settings={"color": "blue"},
        )

        self.assertEqual(updated.name, "Backlog")
        self.assertEqual(
            updated.description,
            "Tasks waiting to be started.",
        )
        self.assertEqual(updated.settings, {"color": "blue"})

    def test_admin_can_update_board_list(self):
        updated = update_board_list(
            board_list=self.board_list,
            actor=self.admin,
            name="Review",
        )

        self.assertEqual(updated.name, "Review")

    def test_member_cannot_update_board_list(self):
        with self.assertRaises(ValidationError):
            update_board_list(
                board_list=self.board_list,
                actor=self.member,
                name="Review",
            )

    def test_non_member_cannot_update_board_list(self):
        with self.assertRaises(ValidationError):
            update_board_list(
                board_list=self.board_list,
                actor=self.non_member,
                name="Review",
            )

    def test_archived_list_cannot_be_updated(self):
        self.board_list.is_archived = True
        self.board_list.save(update_fields=["is_archived", "updated_at"])

        with self.assertRaises(ValidationError):
            update_board_list(
                board_list=self.board_list,
                actor=self.owner,
                name="Review",
            )

    def test_deleted_list_cannot_be_updated(self):
        self.board_list.soft_delete()

        with self.assertRaises(ValidationError):
            update_board_list(
                board_list=self.board_list,
                actor=self.owner,
                name="Review",
            )

    def test_empty_name_is_rejected(self):
        with self.assertRaises(ValidationError):
            update_board_list(
                board_list=self.board_list,
                actor=self.owner,
                name="   ",
            )

    def test_duplicate_name_is_rejected(self):
        with self.assertRaises(ValidationError):
            update_board_list(
                board_list=self.board_list,
                actor=self.owner,
                name="In Progress",
            )


class ReorderBoardListTests(BoardListServiceTestCase):

    def setUp(self):
        self.todo = BoardList.objects.get(
            board=self.board,
            position=1,
        )
        self.in_progress = BoardList.objects.get(
            board=self.board,
            position=2,
        )
        self.done = BoardList.objects.get(
            board=self.board,
            position=3,
        )

    def test_owner_can_reorder_board_lists(self):
        reordered = reorder_board_lists(
            board=self.board,
            actor=self.owner,
            ordered_list_ids=[
                self.done.pk,
                self.todo.pk,
                self.in_progress.pk,
            ],
        )

        self.assertEqual(
            [(item.pk, item.position) for item in reordered],
            [
                (self.done.pk, 1),
                (self.todo.pk, 2),
                (self.in_progress.pk, 3),
            ],
        )

    def test_admin_can_reorder_board_lists(self):
        reorder_board_lists(
            board=self.board,
            actor=self.admin,
            ordered_list_ids=[
                self.in_progress.pk,
                self.done.pk,
                self.todo.pk,
            ],
        )

        self.todo.refresh_from_db()
        self.in_progress.refresh_from_db()
        self.done.refresh_from_db()

        self.assertEqual(self.in_progress.position, 1)
        self.assertEqual(self.done.position, 2)
        self.assertEqual(self.todo.position, 3)

    def test_member_cannot_reorder_board_lists(self):
        with self.assertRaises(ValidationError):
            reorder_board_lists(
                board=self.board,
                actor=self.member,
                ordered_list_ids=[
                    self.done.pk,
                    self.todo.pk,
                    self.in_progress.pk,
                ],
            )

    def test_non_member_cannot_reorder_board_lists(self):
        with self.assertRaises(ValidationError):
            reorder_board_lists(
                board=self.board,
                actor=self.non_member,
                ordered_list_ids=[
                    self.done.pk,
                    self.todo.pk,
                    self.in_progress.pk,
                ],
            )

    def test_duplicate_ids_are_rejected(self):
        with self.assertRaises(ValidationError):
            reorder_board_lists(
                board=self.board,
                actor=self.owner,
                ordered_list_ids=[
                    self.todo.pk,
                    self.todo.pk,
                    self.done.pk,
                ],
            )

    def test_missing_list_id_is_rejected(self):
        with self.assertRaises(ValidationError):
            reorder_board_lists(
                board=self.board,
                actor=self.owner,
                ordered_list_ids=[
                    self.todo.pk,
                    self.done.pk,
                ],
            )

    def test_list_from_another_board_is_rejected(self):
        another_board = create_board(
            workspace=self.workspace,
            name="Marketing",
            created_by=self.owner,
        )
        another_list = BoardList.objects.get(
            board=another_board,
            position=1,
        )

        with self.assertRaises(ValidationError):
            reorder_board_lists(
                board=self.board,
                actor=self.owner,
                ordered_list_ids=[
                    self.todo.pk,
                    self.in_progress.pk,
                    another_list.pk,
                ],
            )

    def test_archived_lists_can_be_reordered(self):
        self.done.is_archived = True
        self.done.save(
            update_fields=["is_archived", "updated_at"]
        )

        reorder_board_lists(
            board=self.board,
            actor=self.owner,
            ordered_list_ids=[
                self.done.pk,
                self.todo.pk,
                self.in_progress.pk,
            ],
        )

        self.done.refresh_from_db()
        self.assertEqual(self.done.position, 1)
        self.assertTrue(self.done.is_archived)

    def test_deleted_lists_are_not_included_in_reordering(self):
        self.done.soft_delete()

        reorder_board_lists(
            board=self.board,
            actor=self.owner,
            ordered_list_ids=[
                self.in_progress.pk,
                self.todo.pk,
            ],
        )

        self.in_progress.refresh_from_db()
        self.todo.refresh_from_db()
        self.done.refresh_from_db()

        self.assertEqual(self.in_progress.position, 1)
        self.assertEqual(self.todo.position, 2)
        self.assertEqual(self.done.position, 3)
        self.assertIsNotNone(self.done.deleted_at)

    def test_empty_list_of_ids_is_rejected(self):
        with self.assertRaises(ValidationError):
            reorder_board_lists(
                board=self.board,
                actor=self.owner,
                ordered_list_ids=[],
            )

    def test_reordering_preserves_soft_deleted_positions(self):
        self.todo.soft_delete()

        reordered = reorder_board_lists(
            board=self.board,
            actor=self.owner,
            ordered_list_ids=[
                self.done.pk,
                self.in_progress.pk,
            ],
        )

        self.todo.refresh_from_db()
        self.done.refresh_from_db()
        self.in_progress.refresh_from_db()

        self.assertEqual(self.todo.position, 1)
        self.assertEqual(
            [item.pk for item in reordered],
            [self.done.pk, self.in_progress.pk],
        )
        self.assertEqual(self.done.position, 2)
        self.assertEqual(self.in_progress.position, 3)


class ArchiveBoardListTests(BoardListServiceTestCase):

    def setUp(self):
        self.todo = BoardList.objects.get(
            board=self.board,
            position=1,
        )

        self.in_progress = BoardList.objects.get(
            board=self.board,
            position=2,
        )

        self.done = BoardList.objects.get(
            board=self.board,
            position=3,
        )

    def test_owner_can_archive_board_list(self):
        extra_list = create_board_list(
            board=self.board,
            actor=self.owner,
            name="Testing",
        )

        archived = archive_board_list(
            board_list=extra_list,
            actor=self.owner,
        )

        self.assertTrue(archived.is_archived)
        self.assertIsNone(archived.deleted_at)

    def test_admin_can_archive_board_list(self):
        extra_list = create_board_list(
            board=self.board,
            actor=self.owner,
            name="Testing",
        )

        archived = archive_board_list(
            board_list=extra_list,
            actor=self.admin,
        )

        self.assertTrue(archived.is_archived)

    def test_member_cannot_archive_board_list(self):
        extra_list = create_board_list(
            board=self.board,
            actor=self.owner,
            name="Testing",
        )

        with self.assertRaises(ValidationError):
            archive_board_list(
                board_list=extra_list,
                actor=self.member,
            )

    def test_non_member_cannot_archive_board_list(self):
        extra_list = create_board_list(
            board=self.board,
            actor=self.owner,
            name="Testing",
        )

        with self.assertRaises(ValidationError):
            archive_board_list(
                board_list=extra_list,
                actor=self.non_member,
            )

    def test_cannot_archive_when_only_three_active_lists_remain(self):
        with self.assertRaises(ValidationError):
            archive_board_list(
                board_list=self.todo,
                actor=self.owner,
            )

        self.todo.refresh_from_db()
        self.assertFalse(self.todo.is_archived)

    def test_can_archive_when_more_than_three_active_lists_exist(self):
        extra_list = create_board_list(
            board=self.board,
            actor=self.owner,
            name="Testing",
        )

        archive_board_list(
            board_list=extra_list,
            actor=self.owner,
        )

        self.assertTrue(
            BoardList.objects.filter(
                pk=extra_list.pk,
                is_archived=True,
            ).exists()
        )

    def test_cannot_archive_already_archived_list(self):
        self.todo.is_archived = True
        self.todo.save(
            update_fields=["is_archived", "updated_at"]
        )

        with self.assertRaises(ValidationError):
            archive_board_list(
                board_list=self.todo,
                actor=self.owner,
            )

    def test_cannot_archive_deleted_list(self):
        extra_list = create_board_list(
            board=self.board,
            actor=self.owner,
            name="Testing",
        )
        extra_list.soft_delete()

        with self.assertRaises(ValidationError):
            archive_board_list(
                board_list=extra_list,
                actor=self.owner,
            )

    def test_archived_list_remains_visible_in_default_manager(self):
        extra_list = create_board_list(
            board=self.board,
            actor=self.owner,
            name="Testing",
        )

        archive_board_list(
            board_list=extra_list,
            actor=self.owner,
        )

        self.assertTrue(
            BoardList.objects.filter(pk=extra_list.pk).exists()
        )


class UnarchiveBoardListTests(BoardListServiceTestCase):

    def setUp(self):
        self.todo = BoardList.objects.get(
            board=self.board,
            position=1,
        )

        self.todo.is_archived = True
        self.todo.save(
            update_fields=["is_archived", "updated_at"]
        )

    def test_owner_can_unarchive_board_list(self):
        result = unarchive_board_list(
            board_list=self.todo,
            actor=self.owner,
        )

        self.assertFalse(result.is_archived)

    def test_admin_can_unarchive_board_list(self):
        result = unarchive_board_list(
            board_list=self.todo,
            actor=self.admin,
        )

        self.assertFalse(result.is_archived)

    def test_member_cannot_unarchive_board_list(self):
        with self.assertRaises(ValidationError):
            unarchive_board_list(
                board_list=self.todo,
                actor=self.member,
            )

    def test_non_member_cannot_unarchive_board_list(self):
        with self.assertRaises(ValidationError):
            unarchive_board_list(
                board_list=self.todo,
                actor=self.non_member,
            )

    def test_cannot_unarchive_active_board_list(self):
        self.todo.is_archived = False
        self.todo.save(
            update_fields=["is_archived", "updated_at"]
        )

        with self.assertRaises(ValidationError):
            unarchive_board_list(
                board_list=self.todo,
                actor=self.owner,
            )

    def test_cannot_unarchive_deleted_board_list(self):
        self.todo.soft_delete()

        with self.assertRaises(ValidationError):
            unarchive_board_list(
                board_list=self.todo,
                actor=self.owner,
            )

    def test_unarchiving_preserves_other_fields(self):
        self.todo.description = "Important workflow stage"
        self.todo.settings = {"color": "blue"}
        self.todo.save(
            update_fields=["description", "settings", "updated_at"]
        )

        unarchive_board_list(
            board_list=self.todo,
            actor=self.owner,
        )

        self.todo.refresh_from_db()

        self.assertFalse(self.todo.is_archived)
        self.assertEqual(
            self.todo.description,
            "Important workflow stage",
        )
        self.assertEqual(
            self.todo.settings,
            {"color": "blue"},
        )


class DeleteBoardListTests(BoardListServiceTestCase):

    def setUp(self):
        self.todo = BoardList.objects.get(
            board=self.board,
            position=1,
        )
        self.extra_list = create_board_list(
            board=self.board,
            actor=self.owner,
            name="Testing",
        )

    def test_owner_can_delete_board_list(self):
        result = delete_board_list(
            board_list=self.extra_list,
            actor=self.owner,
        )

        self.assertIsNotNone(result.deleted_at)

    def test_admin_can_delete_board_list(self):
        result = delete_board_list(
            board_list=self.extra_list,
            actor=self.admin,
        )

        self.assertIsNotNone(result.deleted_at)

    def test_member_cannot_delete_board_list(self):
        with self.assertRaises(ValidationError):
            delete_board_list(
                board_list=self.extra_list,
                actor=self.member,
            )

    def test_non_member_cannot_delete_board_list(self):
        with self.assertRaises(ValidationError):
            delete_board_list(
                board_list=self.extra_list,
                actor=self.non_member,
            )

    def test_cannot_delete_when_only_three_active_lists_remain(self):
        # First delete the extra list, leaving exactly three active lists.
        delete_board_list(
            board_list=self.extra_list,
            actor=self.owner,
        )

        with self.assertRaises(ValidationError):
            delete_board_list(
                board_list=self.todo,
                actor=self.owner,
            )

        self.todo.refresh_from_db()
        self.assertIsNone(self.todo.deleted_at)

    def test_can_delete_when_more_than_three_active_lists_exist(self):
        result = delete_board_list(
            board_list=self.extra_list,
            actor=self.owner,
        )

        self.assertIsNotNone(result.deleted_at)

    def test_deleted_list_is_hidden_from_default_manager(self):
        delete_board_list(
            board_list=self.extra_list,
            actor=self.owner,
        )

        self.assertFalse(
            BoardList.objects.filter(pk=self.extra_list.pk).exists()
        )

    def test_deleted_list_remains_in_all_objects(self):
        delete_board_list(
            board_list=self.extra_list,
            actor=self.owner,
        )

        self.assertTrue(
            BoardList.all_objects.filter(pk=self.extra_list.pk).exists()
        )

    def test_deleted_list_keeps_its_position_reserved(self):
        original_position = self.extra_list.position

        delete_board_list(
            board_list=self.extra_list,
            actor=self.owner,
        )

        deleted_list = BoardList.all_objects.get(
            pk=self.extra_list.pk,
        )

        self.assertEqual(deleted_list.position, original_position)

    def test_cannot_delete_already_deleted_list(self):
        self.extra_list.soft_delete()

        with self.assertRaises(ValidationError):
            delete_board_list(
                board_list=self.extra_list,
                actor=self.owner,
            )

    def test_can_delete_archived_list(self):
        extra_list = create_board_list(
            board=self.board,
            actor=self.owner,
            name="Another list",
        )

        self.extra_list.is_archived = True
        self.extra_list.save(
            update_fields=["is_archived", "updated_at"]
        )

        result = delete_board_list(
            board_list=self.extra_list,
            actor=self.owner,
        )

        self.assertIsNotNone(result.deleted_at)
        self.assertTrue(result.is_archived)


class RestoreBoardListTests(BoardListServiceTestCase):

    def setUp(self):
        self.deleted_list = create_board_list(
            board=self.board,
            actor=self.owner,
            name="Deleted list",
        )
        self.original_position = self.deleted_list.position
        self.deleted_list.soft_delete()

    def test_owner_can_restore_board_list(self):
        restored = restore_board_list(
            board_list=self.deleted_list,
            actor=self.owner,
        )

        self.assertIsNone(restored.deleted_at)
        self.assertTrue(
            BoardList.objects.filter(pk=restored.pk).exists()
        )

    def test_admin_can_restore_board_list(self):
        restored = restore_board_list(
            board_list=self.deleted_list,
            actor=self.admin,
        )

        self.assertIsNone(restored.deleted_at)

    def test_member_cannot_restore_board_list(self):
        with self.assertRaises(ValidationError):
            restore_board_list(
                board_list=self.deleted_list,
                actor=self.member,
            )

    def test_non_member_cannot_restore_board_list(self):
        with self.assertRaises(ValidationError):
            restore_board_list(
                board_list=self.deleted_list,
                actor=self.non_member,
            )

    def test_cannot_restore_active_board_list(self):
        active_list = BoardList.objects.get(
            board=self.board,
            position=1,
        )

        with self.assertRaises(ValidationError):
            restore_board_list(
                board_list=active_list,
                actor=self.owner,
            )

    def test_restore_preserves_original_position(self):
        restored = restore_board_list(
            board_list=self.deleted_list,
            actor=self.owner,
        )

        self.assertEqual(
            restored.position,
            self.original_position,
        )

    def test_restore_preserves_archived_status(self):
        self.deleted_list.is_archived = True
        self.deleted_list.save(
            update_fields=["is_archived", "updated_at"]
        )

        restored = restore_board_list(
            board_list=self.deleted_list,
            actor=self.owner,
        )

        self.assertTrue(restored.is_archived)
        self.assertIsNone(restored.deleted_at)

    def test_restored_list_is_visible_in_default_manager(self):
        restore_board_list(
            board_list=self.deleted_list,
            actor=self.owner,
        )

        self.assertTrue(
            BoardList.objects.filter(
                pk=self.deleted_list.pk
            ).exists()
        )

    def test_restore_does_not_change_other_fields(self):
        self.deleted_list.description = "Preserved description"
        self.deleted_list.settings = {"color": "blue"}
        self.deleted_list.save(
            update_fields=["description", "settings", "updated_at"]
        )

        restored = restore_board_list(
            board_list=self.deleted_list,
            actor=self.owner,
        )

        self.assertEqual(
            restored.description,
            "Preserved description",
        )
        self.assertEqual(
            restored.settings,
            {"color": "blue"},
        )