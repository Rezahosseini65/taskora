
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.boards.models import Board
from apps.boards.services import (
    create_board,
    update_board,
    archive_board,
    unarchive_board,
    delete_board,
    restore_board
)
from apps.organizations.models import (
    MembershipStatus as OrganizationMembershipStatus,
    OrganizationRole,
    OrganizationMembership
)
from apps.organizations.services import create_organization
from apps.users.models import User
from apps.workspaces.models import (
    WorkspaceMembership,
    WorkspaceRole,
)
from apps.workspaces.services import create_workspace


class BoardServiceTestCase(TestCase):
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


class CreateBoardTests(BoardServiceTestCase):
    def test_owner_can_create_board(self):
        board = create_board(
            workspace=self.workspace,
            name="Development",
            created_by=self.owner,
        )

        self.assertEqual(board.workspace, self.workspace)
        self.assertEqual(board.created_by, self.owner)
        self.assertEqual(board.name, "Development")
        self.assertEqual(board.slug, "development")
        self.assertEqual(board.settings, {})
        self.assertFalse(board.is_archived)
        self.assertIsNone(board.deleted_at)

    def test_admin_can_create_board(self):
        board = create_board(
            workspace=self.workspace,
            name="Marketing",
            created_by=self.admin,
        )

        self.assertEqual(board.created_by, self.admin)
        self.assertEqual(board.name, "Marketing")

    def test_member_cannot_create_board(self):
        with self.assertRaises(ValidationError):
            create_board(
                workspace=self.workspace,
                name="Support",
                created_by=self.member,
            )

    def test_non_member_cannot_create_board(self):
        with self.assertRaises(ValidationError):
            create_board(
                workspace=self.workspace,
                name="Private Board",
                created_by=self.non_member,
            )

    def test_cannot_create_board_in_deleted_workspace(self):
        self.workspace.soft_delete()

        with self.assertRaises(ValidationError):
            create_board(
                workspace=self.workspace,
                name="Deleted Workspace Board",
                created_by=self.owner,
            )

    def test_created_board_is_saved_in_database(self):
        board = create_board(
            workspace=self.workspace,
            name="Operations",
            created_by=self.owner,
        )

        self.assertTrue(
            Board.objects.filter(pk=board.pk).exists()
        )


class UpdateBoardTests(BoardServiceTestCase):
    def setUp(self):
        self.board = create_board(
            workspace=self.workspace,
            name="Development",
            created_by=self.owner,
        )

    def test_owner_can_update_board(self):
        board = update_board(
            board=self.board,
            actor=self.owner,
            name="Updated Development",
            description="Updated description",
            settings={"color": "blue"},
        )

        self.assertEqual(board.name, "Updated Development")
        self.assertEqual(board.description, "Updated description")
        self.assertEqual(board.settings, {"color": "blue"})

    def test_admin_can_update_board(self):
        board = update_board(
            board=self.board,
            actor=self.admin,
            name="Marketing",
        )

        self.assertEqual(board.name, "Marketing")

    def test_member_cannot_update_board(self):
        with self.assertRaises(ValidationError):
            update_board(
                board=self.board,
                actor=self.member,
                name="Unauthorized Update",
            )

    def test_non_member_cannot_update_board(self):
        with self.assertRaises(ValidationError):
            update_board(
                board=self.board,
                actor=self.non_member,
                name="Unauthorized Update",
            )

    def test_archived_board_cannot_be_updated(self):
        self.board.is_archived = True
        self.board.save(
            update_fields=["is_archived", "updated_at"]
        )

        with self.assertRaises(ValidationError):
            update_board(
                board=self.board,
                actor=self.owner,
                name="Updated Development",
            )

    def test_deleted_board_cannot_be_updated(self):
        self.board.soft_delete()

        with self.assertRaises(ValidationError):
            update_board(
                board=self.board,
                actor=self.owner,
                name="Updated Development",
            )

    def test_unspecified_fields_remain_unchanged(self):
        original_description = self.board.description
        original_settings = self.board.settings
        original_slug = self.board.slug

        board = update_board(
            board=self.board,
            actor=self.owner,
            name="New Development",
        )

        self.assertEqual(board.name, "New Development")
        self.assertEqual(board.description, original_description)
        self.assertEqual(board.settings, original_settings)
        self.assertEqual(board.slug, original_slug)

    def test_suspended_organization_member_cannot_update_board(self):
        suspended_user = User.objects.create_user(
            email="suspended@example.com",
            password="test-password",
        )

        OrganizationMembership.objects.create(
            organization=self.organization,
            user=suspended_user,
            role=OrganizationRole.MEMBER,
            status=OrganizationMembershipStatus.SUSPENDED,
        )

        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=suspended_user,
            role=WorkspaceRole.ADMIN,
        )

        with self.assertRaises(ValidationError):
            update_board(
                board=self.board,
                actor=suspended_user,
                name="Unauthorized Update",
            )


class ArchiveBoardTests(BoardServiceTestCase):
    def setUp(self):
        self.board = create_board(
            workspace=self.workspace,
            name="Development",
            created_by=self.owner,
        )

    def test_owner_can_archive_board(self):
        board = archive_board(
            board=self.board,
            actor=self.owner,
        )

        self.assertTrue(board.is_archived)
        self.assertIsNone(board.deleted_at)

    def test_admin_can_archive_board(self):
        board = archive_board(
            board=self.board,
            actor=self.admin,
        )

        self.assertTrue(board.is_archived)

    def test_member_cannot_archive_board(self):
        with self.assertRaises(ValidationError):
            archive_board(
                board=self.board,
                actor=self.member,
            )

    def test_non_member_cannot_archive_board(self):
        with self.assertRaises(ValidationError):
            archive_board(
                board=self.board,
                actor=self.non_member,
            )

    def test_cannot_archive_already_archived_board(self):
        self.board.is_archived = True
        self.board.save(
            update_fields=["is_archived", "updated_at"]
        )

        with self.assertRaises(ValidationError):
            archive_board(
                board=self.board,
                actor=self.owner,
            )

    def test_cannot_archive_deleted_board(self):
        self.board.soft_delete()

        with self.assertRaises(ValidationError):
            archive_board(
                board=self.board,
                actor=self.owner,
            )

    def test_owner_can_unarchive_board(self):
        self.board.is_archived = True
        self.board.save(
            update_fields=["is_archived", "updated_at"]
        )

        board = unarchive_board(
            board=self.board,
            actor=self.owner,
        )

        self.assertFalse(board.is_archived)
        self.assertIsNone(board.deleted_at)

    def test_admin_can_unarchive_board(self):
        self.board.is_archived = True
        self.board.save(
            update_fields=["is_archived", "updated_at"]
        )

        board = unarchive_board(
            board=self.board,
            actor=self.admin,
        )

        self.assertFalse(board.is_archived)

    def test_member_cannot_unarchive_board(self):
        self.board.is_archived = True
        self.board.save(
            update_fields=["is_archived", "updated_at"]
        )

        with self.assertRaises(ValidationError):
            unarchive_board(
                board=self.board,
                actor=self.member,
            )

    def test_non_member_cannot_unarchive_board(self):
        self.board.is_archived = True
        self.board.save(
            update_fields=["is_archived", "updated_at"]
        )

        with self.assertRaises(ValidationError):
            unarchive_board(
                board=self.board,
                actor=self.non_member,
            )

    def test_cannot_unarchive_active_board(self):
        with self.assertRaises(ValidationError):
            unarchive_board(
                board=self.board,
                actor=self.owner,
            )

    def test_cannot_unarchive_deleted_board(self):
        self.board.is_archived = True
        self.board.save(
            update_fields=["is_archived", "updated_at"]
        )
        self.board.soft_delete()

        with self.assertRaises(ValidationError):
            unarchive_board(
                board=self.board,
                actor=self.owner,
            )


class DeleteRestoreBoardTests(BoardServiceTestCase):
    def setUp(self):
        self.board = create_board(
            workspace=self.workspace,
            name="Development",
            created_by=self.owner,
        )

    def test_owner_can_delete_board(self):
        board = delete_board(
            board=self.board,
            actor=self.owner,
        )

        self.assertIsNotNone(board.deleted_at)
        self.assertTrue(
            Board.all_objects.filter(pk=board.pk).exists()
        )
        self.assertFalse(
            Board.objects.filter(pk=board.pk).exists()
        )

    def test_admin_can_delete_board(self):
        board = delete_board(
            board=self.board,
            actor=self.admin,
        )

        self.assertIsNotNone(board.deleted_at)

    def test_member_cannot_delete_board(self):
        with self.assertRaises(ValidationError):
            delete_board(
                board=self.board,
                actor=self.member,
            )

    def test_non_member_cannot_delete_board(self):
        with self.assertRaises(ValidationError):
            delete_board(
                board=self.board,
                actor=self.non_member,
            )

    def test_cannot_delete_already_deleted_board(self):
        self.board.soft_delete()

        with self.assertRaises(ValidationError):
            delete_board(
                board=self.board,
                actor=self.owner,
            )

    def test_owner_can_restore_board(self):
        self.board.soft_delete()

        board = restore_board(
            board=self.board,
            actor=self.owner,
        )

        self.assertIsNone(board.deleted_at)
        self.assertTrue(
            Board.objects.filter(pk=board.pk).exists()
        )

    def test_admin_can_restore_board(self):
        self.board.soft_delete()

        board = restore_board(
            board=self.board,
            actor=self.admin,
        )

        self.assertIsNone(board.deleted_at)

    def test_member_cannot_restore_board(self):
        self.board.soft_delete()

        with self.assertRaises(ValidationError):
            restore_board(
                board=self.board,
                actor=self.member,
            )

    def test_non_member_cannot_restore_board(self):
        self.board.soft_delete()

        with self.assertRaises(ValidationError):
            restore_board(
                board=self.board,
                actor=self.non_member,
            )

    def test_cannot_restore_active_board(self):
        with self.assertRaises(ValidationError):
            restore_board(
                board=self.board,
                actor=self.owner,
            )

    def test_cannot_delete_board_in_deleted_workspace(self):
        self.workspace.soft_delete()

        with self.assertRaises(ValidationError):
            delete_board(
                board=self.board,
                actor=self.owner,
            )

    def test_cannot_restore_board_in_deleted_workspace(self):
        self.board.soft_delete()
        self.workspace.soft_delete()

        with self.assertRaises(ValidationError):
            restore_board(
                board=self.board,
                actor=self.owner,
            )

    def test_archive_status_is_preserved_after_delete_and_restore(self):
        self.board.is_archived = True
        self.board.save(
            update_fields=["is_archived", "updated_at"]
        )

        deleted_board = delete_board(
            board=self.board,
            actor=self.owner,
        )

        self.assertTrue(deleted_board.is_archived)

        restored_board = restore_board(
            board=deleted_board,
            actor=self.owner,
        )

        self.assertTrue(restored_board.is_archived)
        self.assertIsNone(restored_board.deleted_at)
