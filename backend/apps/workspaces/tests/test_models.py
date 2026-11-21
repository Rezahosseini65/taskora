
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.organizations.models import Organization
from apps.workspaces.models import (
    MembershipStatus,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)

User = get_user_model()


class WorkspaceModelTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com",
            password="test-password-123",
        )
        self.organization = Organization.objects.create(
            name="Taskora",
            created_by=self.owner,
        )

    def create_workspace(self, **kwargs):
        defaults = {
            "organization": self.organization,
            "name": "Development",
            "created_by": self.owner,
        }
        defaults.update(kwargs)
        return Workspace.objects.create(**defaults)

    def test_create_workspace(self):
        workspace = self.create_workspace()

        self.assertEqual(workspace.name, "Development")
        self.assertEqual(workspace.organization, self.organization)
        self.assertEqual(workspace.created_by, self.owner)
        self.assertEqual(workspace.membership_policy, "private")
        self.assertIsNotNone(workspace.id)

    def test_name_is_stripped_on_save(self):
        workspace = self.create_workspace(name="  Development  ")

        self.assertEqual(workspace.name, "Development")

    def test_name_is_unique_case_insensitively_per_organization(self):
        self.create_workspace(name="development")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_workspace(name="Development")

    def test_same_name_is_allowed_in_different_organizations(self):
        second_organization = Organization.objects.create(
            name="Another Company",
            created_by=self.owner,
        )

        first = self.create_workspace(name="Development")
        second = self.create_workspace(
            organization=second_organization,
            name="Development",
        )

        self.assertNotEqual(first.pk, second.pk)

    def test_slug_is_generated_when_empty(self):
        workspace = self.create_workspace(name="Development Team")

        self.assertEqual(workspace.slug, "development-team")

    def test_custom_slug_is_preserved(self):
        workspace = self.create_workspace(slug="custom-workspace")

        self.assertEqual(workspace.slug, "custom-workspace")

    def test_duplicate_slug_is_rejected_per_organization(self):
        self.create_workspace(slug="development")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_workspace(
                    name="Another Workspace",
                    slug="development",
                )

    def test_same_slug_is_allowed_in_different_organizations(self):
        second_organization = Organization.objects.create(
            name="Another Company",
            created_by=self.owner,
        )

        first = self.create_workspace(slug="development")
        second = self.create_workspace(
            organization=second_organization,
            name="Development",
            slug="development",
        )

        self.assertNotEqual(first.pk, second.pk)

    def test_objects_excludes_soft_deleted_workspaces(self):
        workspace = self.create_workspace()
        workspace.soft_delete()

        self.assertFalse(
            Workspace.objects.filter(pk=workspace.pk).exists()
        )
        self.assertTrue(
            Workspace.all_objects.filter(pk=workspace.pk).exists()
        )

    def test_soft_delete(self):
        workspace = self.create_workspace()

        workspace.soft_delete()
        workspace.refresh_from_db()

        self.assertTrue(workspace.is_deleted)
        self.assertIsNotNone(workspace.deleted_at)

    def test_soft_delete_is_idempotent(self):
        workspace = self.create_workspace()
        workspace.soft_delete()
        deleted_at = workspace.deleted_at

        workspace.soft_delete()
        workspace.refresh_from_db()

        self.assertEqual(workspace.deleted_at, deleted_at)

    def test_restore(self):
        workspace = self.create_workspace()
        workspace.soft_delete()
        workspace.restore()
        workspace.refresh_from_db()

        self.assertFalse(workspace.is_deleted)
        self.assertIsNone(workspace.deleted_at)

    def test_deleted_workspace_name_remains_reserved(self):
        self.create_workspace(name="Development").soft_delete()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_workspace(name="DEVELOPMENT")

    def test_deleted_workspace_slug_remains_reserved(self):
        self.create_workspace(slug="development").soft_delete()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_workspace(
                    name="Another Workspace",
                    slug="development",
                )

    def test_save_rejects_name_that_cannot_generate_slug(self):
        workspace = Workspace(
            organization=self.organization,
            name="!!!",
            created_by=self.owner,
        )

        with self.assertRaises(ValidationError):
            workspace.save()


class WorkspaceMembershipModelTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com",
            password="test-password-123",
        )
        self.member = User.objects.create_user(
            email="member@example.com",
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

    def create_membership(self, **kwargs):
        defaults = {
            "workspace": self.workspace,
            "user": self.member,
        }
        defaults.update(kwargs)
        return WorkspaceMembership.objects.create(**defaults)

    def test_create_membership(self):
        membership = self.create_membership()

        self.assertEqual(membership.workspace, self.workspace)
        self.assertEqual(membership.user, self.member)
        self.assertEqual(membership.role, WorkspaceRole.MEMBER)
        self.assertEqual(membership.status, MembershipStatus.ACTIVE)
        self.assertIsNotNone(membership.joined_at)

    def test_user_can_join_multiple_workspaces(self):
        second_workspace = Workspace.objects.create(
            organization=self.organization,
            name="Design",
            created_by=self.owner,
        )

        first = self.create_membership()
        second = WorkspaceMembership.objects.create(
            workspace=second_workspace,
            user=self.member,
        )

        self.assertNotEqual(first.pk, second.pk)

    def test_duplicate_membership_is_rejected(self):
        self.create_membership()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_membership()

    def test_only_one_active_owner_per_workspace(self):
        self.create_membership(
            user=self.owner,
            role=WorkspaceRole.OWNER,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_membership(
                    user=self.member,
                    role=WorkspaceRole.OWNER,
                )

    def test_suspended_owner_does_not_block_another_active_owner(self):
        self.create_membership(
            user=self.owner,
            role=WorkspaceRole.OWNER,
            status=MembershipStatus.SUSPENDED,
        )

        membership = self.create_membership(
            user=self.member,
            role=WorkspaceRole.OWNER,
        )

        self.assertEqual(membership.role, WorkspaceRole.OWNER)
        self.assertEqual(membership.status, MembershipStatus.ACTIVE)

    def test_left_membership_does_not_block_new_active_owner(self):
        self.create_membership(
            user=self.owner,
            role=WorkspaceRole.OWNER,
            status=MembershipStatus.LEFT,
        )

        membership = self.create_membership(
            user=self.member,
            role=WorkspaceRole.OWNER,
        )

        self.assertEqual(membership.role, WorkspaceRole.OWNER)
        self.assertEqual(membership.status, MembershipStatus.ACTIVE)

    def test_rejoining_user_reuses_existing_membership(self):
        membership = self.create_membership(
            status=MembershipStatus.LEFT,
        )
        original_id = membership.pk

        membership.status = MembershipStatus.ACTIVE
        membership.joined_at = timezone.now()
        membership.save()

        membership.refresh_from_db()

        self.assertEqual(membership.pk, original_id)
        self.assertEqual(membership.status, MembershipStatus.ACTIVE)
