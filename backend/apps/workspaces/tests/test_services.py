from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.organizations.models import (
    MembershipStatus as OrganizationMembershipStatus,
    Organization,
    OrganizationMembership ,
    OrganizationRole,
)
from apps.workspaces.models import (
    MembershipStatus,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)
from apps.workspaces.services import (
    create_workspace,
    join_workspace,
    leave_workspace,
    transfer_workspace_ownership,
    suspend_workspace_membership,
    reactivate_workspace_membership,
    change_workspace_member_role,
    delete_workspace,
    restore_workspace,
)

User = get_user_model()


class CreateWorkspaceServiceTests(TestCase):

    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com",
            password="test-password-123",
        )
        self.admin = User.objects.create_user(
            email="admin@example.com",
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

        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.owner,
            role=OrganizationRole.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.admin,
            role=OrganizationRole.ADMIN,
        )
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.member,
            role=OrganizationRole.MEMBER,
        )

    def test_owner_can_create_workspace(self):
        workspace = create_workspace(
            organization=self.organization,
            name="Development",
            created_by=self.owner,
        )

        self.assertEqual(workspace.created_by, self.owner)
        self.assertTrue(
            WorkspaceMembership.objects.filter(
                workspace=workspace,
                user=self.owner,
                role=WorkspaceRole.OWNER,
                status=MembershipStatus.ACTIVE,
            ).exists()
        )

    def test_admin_can_create_workspace(self):
        workspace = create_workspace(
            organization=self.organization,
            name="Design",
            created_by=self.admin,
        )

        self.assertEqual(workspace.created_by, self.admin)

    def test_regular_member_cannot_create_workspace(self):
        with self.assertRaises(ValidationError):
            create_workspace(
                organization=self.organization,
                name="Testing",
                created_by=self.member,
            )

        self.assertFalse(
            Workspace.objects.filter(name="Testing").exists()
        )

    def test_non_member_cannot_create_workspace(self):
        outsider = User.objects.create_user(
            email="outsider@example.com",
            password="test-password-123",
        )

        with self.assertRaises(ValidationError):
            create_workspace(
                organization=self.organization,
                name="External",
                created_by=outsider,
            )

    def test_deleted_organization_cannot_create_workspace(self):
        self.organization.soft_delete()

        with self.assertRaises(ValidationError):
            create_workspace(
                organization=self.organization,
                name="Deleted Organization Workspace",
                created_by=self.owner,
            )

    def test_workspace_and_owner_membership_are_created_together(self):
        workspace = create_workspace(
            organization=self.organization,
            name="Atomic Workspace",
            created_by=self.owner,
        )

        self.assertTrue(
            Workspace.objects.filter(pk=workspace.pk).exists()
        )
        self.assertTrue(
            WorkspaceMembership.objects.filter(
                workspace=workspace,
                user=self.owner,
                role=WorkspaceRole.OWNER,
                status=MembershipStatus.ACTIVE,
            ).exists()
        )


class JoinWorkspaceServiceTests(TestCase):
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

        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.owner,
            role=OrganizationRole.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.member,
            role=OrganizationRole.MEMBER,
        )

        self.workspace = Workspace.objects.create(
            organization=self.organization,
            name="Development",
            created_by=self.owner,
            membership_policy="public",
        )

    def test_active_organization_member_can_join_public_workspace(self):
        membership = join_workspace(
            workspace=self.workspace,
            user=self.member,
        )

        self.assertEqual(membership.role, WorkspaceRole.MEMBER)
        self.assertEqual(membership.status, MembershipStatus.ACTIVE)

    def test_non_member_of_organization_cannot_join_workspace(self):
        outsider = User.objects.create_user(
            email="outsider@example.com",
            password="test-password-123",
        )

        with self.assertRaises(ValidationError):
            join_workspace(
                workspace=self.workspace,
                user=outsider,
            )

    def test_suspended_organization_member_cannot_join_workspace(self):
        OrganizationMembership.objects.filter(
            organization=self.organization,
            user=self.member,
        ).update(status=OrganizationMembershipStatus.SUSPENDED)

        with self.assertRaises(ValidationError):
            join_workspace(
                workspace=self.workspace,
                user=self.member,
            )

    def test_private_workspace_rejects_direct_membership(self):
        self.workspace.membership_policy = "private"
        self.workspace.save(update_fields=["membership_policy"])

        with self.assertRaises(ValidationError):
            join_workspace(
                workspace=self.workspace,
                user=self.member,
            )

    def test_existing_active_membership_is_rejected(self):
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=self.member,
        )

        with self.assertRaises(ValidationError):
            join_workspace(
                workspace=self.workspace,
                user=self.member,
            )

    def test_suspended_workspace_membership_cannot_rejoin(self):
        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=self.member,
            status=MembershipStatus.SUSPENDED,
        )

        with self.assertRaises(ValidationError):
            join_workspace(
                workspace=self.workspace,
                user=self.member,
            )

    def test_left_membership_is_reactivated(self):
        old_membership = WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=self.member,
            status=MembershipStatus.LEFT,
        )
        old_id = old_membership.pk

        membership = join_workspace(
            workspace=self.workspace,
            user=self.member,
        )

        self.assertEqual(membership.pk, old_id)
        self.assertEqual(membership.status, MembershipStatus.ACTIVE)
        self.assertEqual(membership.role, WorkspaceRole.MEMBER)


class LeaveWorkspaceServiceTests(TestCase):
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

        WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=self.owner,
            role=WorkspaceRole.OWNER,
        )

        self.membership = WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=self.member,
            role=WorkspaceRole.MEMBER,
        )

    def test_active_member_can_leave_workspace(self):
        membership = leave_workspace(
            workspace=self.workspace,
            user=self.member,
        )

        self.assertEqual(membership.status, MembershipStatus.LEFT)

    def test_membership_record_is_not_deleted(self):
        membership_id = self.membership.pk

        leave_workspace(
            workspace=self.workspace,
            user=self.member,
        )

        self.assertTrue(
            WorkspaceMembership.objects.filter(
                pk=membership_id,
                status=MembershipStatus.LEFT,
            ).exists()
        )

    def test_workspace_owner_cannot_leave(self):
        with self.assertRaises(ValidationError):
            leave_workspace(
                workspace=self.workspace,
                user=self.owner,
            )

        self.assertEqual(
            WorkspaceMembership.objects.get(
                workspace=self.workspace,
                user=self.owner,
            ).status,
            MembershipStatus.ACTIVE,
        )

    def test_non_member_cannot_leave(self):
        outsider = User.objects.create_user(
            email="outsider@example.com",
            password="test-password-123",
        )

        with self.assertRaises(ValidationError):
            leave_workspace(
                workspace=self.workspace,
                user=outsider,
            )

    def test_suspended_member_cannot_leave(self):
        self.membership.status = MembershipStatus.SUSPENDED
        self.membership.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            leave_workspace(
                workspace=self.workspace,
                user=self.member,
            )

    def test_left_member_cannot_leave_again(self):
        self.membership.status = MembershipStatus.LEFT
        self.membership.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            leave_workspace(
                workspace=self.workspace,
                user=self.member,
            )


class TransferWorkspaceOwnershipServiceTests(TestCase):
    def setUp(self):

        self.owner = User.objects.create_user(
            email="owner@example.com",
            password="test-password-123",
        )
        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="test-password-123",
        )
        self.member = User.objects.create_user(
            email="member@example.com",
            password="test-password-123",
        )
        self.outsider = User.objects.create_user(
            email="outsider@example.com",
            password="test-password-123",
        )

        self.organization = Organization.objects.create(
            name="Transfer Test Organization",
            created_by=self.owner,
        )

        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.owner,
            role=OrganizationRole.OWNER,
            status=OrganizationMembershipStatus.ACTIVE,
        )
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.admin,
            role=OrganizationRole.ADMIN,
            status=OrganizationMembershipStatus.ACTIVE,
        )
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.member,
            role=OrganizationRole.MEMBER,
            status=OrganizationMembershipStatus.ACTIVE,
        )

        self.workspace = Workspace.objects.create(
            organization=self.organization,
            name="Transfer Test Workspace",
            created_by=self.owner,
        )

        self.owner_membership = WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=self.owner,
            role=WorkspaceRole.OWNER,
            status=MembershipStatus.ACTIVE,
        )
        self.admin_membership = WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=self.admin,
            role=WorkspaceRole.ADMIN,
            status=MembershipStatus.ACTIVE,
        )
        self.member_membership = WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=self.member,
            role=WorkspaceRole.MEMBER,
            status=MembershipStatus.ACTIVE,
        )

    def test_owner_can_transfer_ownership_to_active_member(self):
        result = transfer_workspace_ownership(
            self.workspace,
            self.owner,
            self.member,
        )

        self.owner_membership.refresh_from_db()
        self.member_membership.refresh_from_db()

        self.assertEqual(result.pk, self.member_membership.pk)
        self.assertEqual(self.owner_membership.role, WorkspaceRole.ADMIN)
        self.assertEqual(self.member_membership.role, WorkspaceRole.OWNER)

    def test_admin_cannot_transfer_ownership(self):
        with self.assertRaises(ValidationError):
            transfer_workspace_ownership(
                self.workspace,
                self.admin,
                self.member,
            )

        self.owner_membership.refresh_from_db()
        self.assertEqual(self.owner_membership.role, WorkspaceRole.OWNER)

    def test_cannot_transfer_ownership_to_self(self):
        with self.assertRaises(ValidationError):
            transfer_workspace_ownership(
                self.workspace,
                self.owner,
                self.owner,
            )

        self.owner_membership.refresh_from_db()
        self.assertEqual(self.owner_membership.role, WorkspaceRole.OWNER)

    def test_new_owner_must_be_workspace_member(self):
        with self.assertRaises(ValidationError):
            transfer_workspace_ownership(
                self.workspace,
                self.owner,
                self.outsider,
            )

        self.owner_membership.refresh_from_db()
        self.assertEqual(self.owner_membership.role, WorkspaceRole.OWNER)

    def test_new_owner_must_be_active_organization_member(self):
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.outsider,
            role=OrganizationRole.MEMBER,
            status=OrganizationMembershipStatus.LEFT,
        )
        outsider_workspace_membership = WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=self.outsider,
            role=WorkspaceRole.MEMBER,
            status=MembershipStatus.ACTIVE,
        )

        with self.assertRaises(ValidationError):
            transfer_workspace_ownership(
                self.workspace,
                self.owner,
                self.outsider,
            )

        self.owner_membership.refresh_from_db()
        outsider_workspace_membership.refresh_from_db()

        self.assertEqual(self.owner_membership.role, WorkspaceRole.OWNER)
        self.assertEqual(
            outsider_workspace_membership.role,
            WorkspaceRole.MEMBER,
        )

    def test_new_owner_must_have_active_workspace_membership(self):
        self.member_membership.status = MembershipStatus.SUSPENDED
        self.member_membership.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            transfer_workspace_ownership(
                self.workspace,
                self.owner,
                self.member,
            )

        self.owner_membership.refresh_from_db()
        self.assertEqual(self.owner_membership.role, WorkspaceRole.OWNER)

    def test_new_owner_can_be_admin(self):
        result = transfer_workspace_ownership(
            self.workspace,
            self.owner,
            self.admin,
        )

        self.owner_membership.refresh_from_db()
        self.admin_membership.refresh_from_db()

        self.assertEqual(result.role, WorkspaceRole.OWNER)
        self.assertEqual(self.owner_membership.role, WorkspaceRole.ADMIN)
        self.assertEqual(self.admin_membership.role, WorkspaceRole.OWNER)

    def test_only_one_active_owner_remains_after_transfer(self):
        transfer_workspace_ownership(
            self.workspace,
            self.owner,
            self.member,
        )

        active_owners = WorkspaceMembership.objects.filter(
            workspace=self.workspace,
            role=WorkspaceRole.OWNER,
            status=MembershipStatus.ACTIVE,
        )

        self.assertEqual(active_owners.count(), 1)
        self.assertEqual(active_owners.get().user, self.member)


class SuspendWorkspaceMembershipTests(TestCase):
    def setUp(self):
        self.User = get_user_model()

        self.owner = self.User.objects.create_user(
            email="owner@example.com",
            password="testpass123",
        )
        self.admin = self.User.objects.create_user(
            email="admin@example.com",
            password="testpass123",
        )
        self.admin2 = self.User.objects.create_user(
            email="admin2@example.com",
            password="testpass123",
        )
        self.member = self.User.objects.create_user(
            email="member@example.com",
            password="testpass123",
        )
        self.member2 = self.User.objects.create_user(
            email="member2@example.com",
            password="testpass123",
        )
        self.outsider = self.User.objects.create_user(
            email="outsider@example.com",
            password="testpass123",
        )

        self.organization = Organization.objects.create(
            name="Test Organization",
            created_by=self.owner,
        )

        self.org_users = [
            (self.owner, OrganizationRole.OWNER),
            (self.admin, OrganizationRole.ADMIN),
            (self.admin2, OrganizationRole.ADMIN),
            (self.member, OrganizationRole.MEMBER),
            (self.member2, OrganizationRole.MEMBER),
        ]

        for user, role in self.org_users:
            OrganizationMembership.objects.create(
                organization=self.organization,
                user=user,
                role=role,
                status=OrganizationMembershipStatus.ACTIVE,
            )

        self.workspace = Workspace.objects.create(
            organization=self.organization,
            name="Test Workspace",
            created_by=self.owner,
        )

        self.owner_membership = self.create_workspace_membership(
            self.owner,
            WorkspaceRole.OWNER,
        )
        self.admin_membership = self.create_workspace_membership(
            self.admin,
            WorkspaceRole.ADMIN,
        )
        self.admin2_membership = self.create_workspace_membership(
            self.admin2,
            WorkspaceRole.ADMIN,
        )
        self.member_membership = self.create_workspace_membership(
            self.member,
            WorkspaceRole.MEMBER,
        )
        self.member2_membership = self.create_workspace_membership(
            self.member2,
            WorkspaceRole.MEMBER,
        )

    def create_workspace_membership(self, user, role):
        return WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=user,
            role=role,
            status=MembershipStatus.ACTIVE,
        )

    def suspend(self, actor, user):
        return suspend_workspace_membership(
            workspace=self.workspace,
            actor=actor,
            user=user,
        )

    def test_owner_can_suspend_member(self):
        membership = self.suspend(self.owner, self.member)

        self.assertEqual(
            membership.status,
            MembershipStatus.SUSPENDED,
        )

    def test_owner_can_suspend_admin(self):
        membership = self.suspend(self.owner, self.admin)

        self.assertEqual(
            membership.status,
            MembershipStatus.SUSPENDED,
        )

    def test_admin_can_suspend_member(self):
        membership = self.suspend(self.admin, self.member)

        self.assertEqual(
            membership.status,
            MembershipStatus.SUSPENDED,
        )

    def test_admin_cannot_suspend_another_admin(self):
        with self.assertRaises(ValidationError):
            self.suspend(self.admin, self.admin2)

        self.admin2_membership.refresh_from_db()

        self.assertEqual(
            self.admin2_membership.status,
            MembershipStatus.ACTIVE,
        )

    def test_admin_cannot_suspend_owner(self):
        with self.assertRaises(ValidationError):
            self.suspend(self.admin, self.owner)

        self.owner_membership.refresh_from_db()

        self.assertEqual(
            self.owner_membership.status,
            MembershipStatus.ACTIVE,
        )

    def test_member_cannot_suspend_another_member(self):
        with self.assertRaises(ValidationError):
            self.suspend(self.member, self.member2)

        self.member2_membership.refresh_from_db()

        self.assertEqual(
            self.member2_membership.status,
            MembershipStatus.ACTIVE,
        )

    def test_non_member_cannot_suspend_member(self):
        with self.assertRaises(ValidationError):
            self.suspend(self.outsider, self.member)

        self.member_membership.refresh_from_db()

        self.assertEqual(
            self.member_membership.status,
            MembershipStatus.ACTIVE,
        )

    def test_inactive_admin_cannot_suspend_member(self):
        self.admin_membership.status = MembershipStatus.SUSPENDED
        self.admin_membership.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            self.suspend(self.admin, self.member)

    def test_left_admin_cannot_suspend_member(self):
        self.admin_membership.status = MembershipStatus.LEFT
        self.admin_membership.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            self.suspend(self.admin, self.member)

    def test_cannot_suspend_nonexistent_membership(self):
        with self.assertRaises(ValidationError):
            self.suspend(self.owner, self.outsider)

    def test_cannot_suspend_already_suspended_membership(self):
        self.member_membership.status = MembershipStatus.SUSPENDED
        self.member_membership.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            self.suspend(self.owner, self.member)

    def test_cannot_suspend_left_membership(self):
        self.member_membership.status = MembershipStatus.LEFT
        self.member_membership.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            self.suspend(self.owner, self.member)

    def test_suspension_does_not_delete_membership(self):
        self.suspend(self.owner, self.member)

        self.assertTrue(
            WorkspaceMembership.objects.filter(
                workspace=self.workspace,
                user=self.member,
            ).exists()
        )

    def test_suspension_does_not_change_organization_membership(self):
        self.suspend(self.owner, self.member)

        org_membership = OrganizationMembership.objects.get(
            organization=self.organization,
            user=self.member,
        )

        self.assertEqual(
            org_membership.status,
            OrganizationMembershipStatus.ACTIVE,
        )

    def test_suspension_does_not_change_membership_role(self):
        self.suspend(self.owner, self.member)

        self.member_membership.refresh_from_db()

        self.assertEqual(
            self.member_membership.role,
            WorkspaceRole.MEMBER,
        )

    def test_workspace_owner_can_suspend_multiple_members(self):
        self.suspend(self.owner, self.member)
        self.suspend(self.owner, self.admin)

        self.member_membership.refresh_from_db()
        self.admin_membership.refresh_from_db()

        self.assertEqual(
            self.member_membership.status,
            MembershipStatus.SUSPENDED,
        )
        self.assertEqual(
            self.admin_membership.status,
            MembershipStatus.SUSPENDED,
        )


class ReactivateWorkspaceMembershipTests(TestCase):
    def setUp(self):
        self.User = get_user_model()

        self.owner = self.User.objects.create_user(
            email="owner-reactivate@example.com",
            password="testpass123",
        )
        self.admin = self.User.objects.create_user(
            email="admin-reactivate@example.com",
            password="testpass123",
        )
        self.admin2 = self.User.objects.create_user(
            email="admin2-reactivate@example.com",
            password="testpass123",
        )
        self.member = self.User.objects.create_user(
            email="member-reactivate@example.com",
            password="testpass123",
        )
        self.member2 = self.User.objects.create_user(
            email="member2-reactivate@example.com",
            password="testpass123",
        )
        self.outsider = self.User.objects.create_user(
            email="outsider-reactivate@example.com",
            password="testpass123",
        )

        self.organization = Organization.objects.create(
            name="Reactivate Test Organization",
            created_by=self.owner,
        )

        self.org_users = [
            (self.owner, OrganizationRole.OWNER),
            (self.admin, OrganizationRole.ADMIN),
            (self.admin2, OrganizationRole.ADMIN),
            (self.member, OrganizationRole.MEMBER),
            (self.member2, OrganizationRole.MEMBER),
        ]

        for user, role in self.org_users:
            OrganizationMembership.objects.create(
                organization=self.organization,
                user=user,
                role=role,
                status=OrganizationMembershipStatus.ACTIVE,
            )

        self.workspace = Workspace.objects.create(
            organization=self.organization,
            name="Reactivate Test Workspace",
            created_by=self.owner,
        )

        self.owner_membership = self.create_workspace_membership(
            self.owner,
            WorkspaceRole.OWNER,
            MembershipStatus.ACTIVE,
        )
        self.admin_membership = self.create_workspace_membership(
            self.admin,
            WorkspaceRole.ADMIN,
            MembershipStatus.ACTIVE,
        )
        self.admin2_membership = self.create_workspace_membership(
            self.admin2,
            WorkspaceRole.ADMIN,
            MembershipStatus.ACTIVE,
        )
        self.member_membership = self.create_workspace_membership(
            self.member,
            WorkspaceRole.MEMBER,
            MembershipStatus.SUSPENDED,
        )
        self.member2_membership = self.create_workspace_membership(
            self.member2,
            WorkspaceRole.MEMBER,
            MembershipStatus.SUSPENDED,
        )

    def create_workspace_membership(self, user, role, status):
        return WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=user,
            role=role,
            status=status,
        )

    def reactivate(self, actor, user):
        return reactivate_workspace_membership(
            workspace=self.workspace,
            actor=actor,
            user=user,
        )

    def test_owner_can_reactivate_member(self):
        membership = self.reactivate(self.owner, self.member)

        self.assertEqual(membership.status, MembershipStatus.ACTIVE)

    def test_owner_can_reactivate_admin(self):
        self.admin_membership.status = MembershipStatus.SUSPENDED
        self.admin_membership.save(update_fields=["status"])

        membership = self.reactivate(self.owner, self.admin)

        self.assertEqual(membership.status, MembershipStatus.ACTIVE)

    def test_admin_can_reactivate_member(self):
        membership = self.reactivate(self.admin, self.member)

        self.assertEqual(membership.status, MembershipStatus.ACTIVE)

    def test_admin_cannot_reactivate_another_admin(self):
        self.admin2_membership.status = MembershipStatus.SUSPENDED
        self.admin2_membership.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            self.reactivate(self.admin, self.admin2)

        self.admin2_membership.refresh_from_db()
        self.assertEqual(
            self.admin2_membership.status,
            MembershipStatus.SUSPENDED,
        )

    def test_admin_cannot_reactivate_owner(self):
        self.owner_membership.status = MembershipStatus.SUSPENDED
        self.owner_membership.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            self.reactivate(self.admin, self.owner)

        self.owner_membership.refresh_from_db()
        self.assertEqual(
            self.owner_membership.status,
            MembershipStatus.SUSPENDED,
        )

    def test_member_cannot_reactivate_another_member(self):
        with self.assertRaises(ValidationError):
            self.reactivate(self.member, self.member2)

    def test_non_member_cannot_reactivate_member(self):
        with self.assertRaises(ValidationError):
            self.reactivate(self.outsider, self.member)

    def test_suspended_admin_cannot_reactivate_member(self):
        self.admin_membership.status = MembershipStatus.SUSPENDED
        self.admin_membership.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            self.reactivate(self.admin, self.member)

    def test_left_admin_cannot_reactivate_member(self):
        self.admin_membership.status = MembershipStatus.LEFT
        self.admin_membership.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            self.reactivate(self.admin, self.member)

    def test_cannot_reactivate_nonexistent_membership(self):
        with self.assertRaises(ValidationError):
            self.reactivate(self.owner, self.outsider)

    def test_cannot_reactivate_active_membership(self):
        self.member_membership.status = MembershipStatus.ACTIVE
        self.member_membership.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            self.reactivate(self.owner, self.member)

    def test_cannot_reactivate_left_membership(self):
        self.member_membership.status = MembershipStatus.LEFT
        self.member_membership.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            self.reactivate(self.owner, self.member)

    def test_user_must_be_active_organization_member(self):
        org_membership = OrganizationMembership.objects.get(
            organization=self.organization,
            user=self.member,
        )
        org_membership.status = OrganizationMembershipStatus.SUSPENDED
        org_membership.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            self.reactivate(self.owner, self.member)

    def test_actor_must_be_active_organization_member(self):
        org_membership = OrganizationMembership.objects.get(
            organization=self.organization,
            user=self.admin,
        )
        org_membership.status = OrganizationMembershipStatus.SUSPENDED
        org_membership.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            self.reactivate(self.admin, self.member)

    def test_reactivation_preserves_membership_role(self):
        self.reactivate(self.owner, self.member)

        self.member_membership.refresh_from_db()
        self.assertEqual(
            self.member_membership.role,
            WorkspaceRole.MEMBER,
        )

    def test_reactivation_does_not_delete_membership(self):
        self.reactivate(self.owner, self.member)

        self.assertTrue(
            WorkspaceMembership.objects.filter(
                workspace=self.workspace,
                user=self.member,
            ).exists()
        )

    def test_reactivation_does_not_change_organization_membership(self):
        self.reactivate(self.owner, self.member)

        org_membership = OrganizationMembership.objects.get(
            organization=self.organization,
            user=self.member,
        )

        self.assertEqual(
            org_membership.status,
            OrganizationMembershipStatus.ACTIVE,
        )


class ChangeWorkspaceMemberRoleTests(TestCase):
    def setUp(self):
        self.User = get_user_model()

        self.owner = self.User.objects.create_user(
            email="owner-role@example.com",
            password="testpass123",
        )
        self.admin = self.User.objects.create_user(
            email="admin-role@example.com",
            password="testpass123",
        )
        self.member = self.User.objects.create_user(
            email="member-role@example.com",
            password="testpass123",
        )
        self.member2 = self.User.objects.create_user(
            email="member2-role@example.com",
            password="testpass123",
        )
        self.outsider = self.User.objects.create_user(
            email="outsider-role@example.com",
            password="testpass123",
        )

        self.organization = Organization.objects.create(
            name="Role Test Organization",
            created_by=self.owner,
        )

        self.org_users = [
            (self.owner, OrganizationRole.OWNER),
            (self.admin, OrganizationRole.ADMIN),
            (self.member, OrganizationRole.MEMBER),
            (self.member2, OrganizationRole.MEMBER),
        ]

        for user, role in self.org_users:
            OrganizationMembership.objects.create(
                organization=self.organization,
                user=user,
                role=role,
                status=OrganizationMembershipStatus.ACTIVE,
            )

        self.workspace = Workspace.objects.create(
            organization=self.organization,
            name="Role Test Workspace",
            created_by=self.owner,
        )

        self.owner_membership = self.create_workspace_membership(
            self.owner,
            WorkspaceRole.OWNER,
        )
        self.admin_membership = self.create_workspace_membership(
            self.admin,
            WorkspaceRole.ADMIN,
        )
        self.member_membership = self.create_workspace_membership(
            self.member,
            WorkspaceRole.MEMBER,
        )
        self.member2_membership = self.create_workspace_membership(
            self.member2,
            WorkspaceRole.MEMBER,
        )

    def create_workspace_membership(self, user, role):
        return WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=user,
            role=role,
            status=MembershipStatus.ACTIVE,
        )

    def change_role(self, actor, user, new_role):
        return change_workspace_member_role(
            workspace=self.workspace,
            actor=actor,
            user=user,
            new_role=new_role,
        )

    def test_owner_can_promote_member_to_admin(self):
        membership = self.change_role(
            self.owner,
            self.member,
            WorkspaceRole.ADMIN,
        )

        self.assertEqual(membership.role, WorkspaceRole.ADMIN)

    def test_owner_can_demote_admin_to_member(self):
        membership = self.change_role(
            self.owner,
            self.admin,
            WorkspaceRole.MEMBER,
        )

        self.assertEqual(membership.role, WorkspaceRole.MEMBER)

    def test_admin_cannot_change_member_role(self):
        with self.assertRaises(ValidationError):
            self.change_role(
                self.admin,
                self.member,
                WorkspaceRole.ADMIN,
            )

        self.member_membership.refresh_from_db()
        self.assertEqual(
            self.member_membership.role,
            WorkspaceRole.MEMBER,
        )

    def test_member_cannot_change_member_role(self):
        with self.assertRaises(ValidationError):
            self.change_role(
                self.member,
                self.member2,
                WorkspaceRole.ADMIN,
            )

    def test_non_member_cannot_change_member_role(self):
        with self.assertRaises(ValidationError):
            self.change_role(
                self.outsider,
                self.member,
                WorkspaceRole.ADMIN,
            )

    def test_owner_cannot_change_own_role(self):
        with self.assertRaises(ValidationError):
            self.change_role(
                self.owner,
                self.owner,
                WorkspaceRole.MEMBER,
            )

        self.owner_membership.refresh_from_db()
        self.assertEqual(
            self.owner_membership.role,
            WorkspaceRole.OWNER,
        )

    def test_owner_role_cannot_be_changed(self):
        # Even if another owner somehow exists, OWNER role
        # must only be changed through ownership transfer.
        self.owner_membership.role = WorkspaceRole.ADMIN
        self.owner_membership.save(update_fields=["role"])

        with self.assertRaises(ValidationError):
            self.change_role(
                self.admin,
                self.owner,
                WorkspaceRole.MEMBER,
            )

    def test_suspended_membership_role_cannot_be_changed(self):
        self.member_membership.status = MembershipStatus.SUSPENDED
        self.member_membership.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            self.change_role(
                self.owner,
                self.member,
                WorkspaceRole.ADMIN,
            )

    def test_left_membership_role_cannot_be_changed(self):
        self.member_membership.status = MembershipStatus.LEFT
        self.member_membership.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            self.change_role(
                self.owner,
                self.member,
                WorkspaceRole.ADMIN,
            )

    def test_nonexistent_membership_role_cannot_be_changed(self):
        with self.assertRaises(ValidationError):
            self.change_role(
                self.owner,
                self.outsider,
                WorkspaceRole.ADMIN,
            )

    def test_invalid_new_role_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.change_role(
                self.owner,
                self.member,
                "INVALID",
            )

    def test_same_role_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.change_role(
                self.owner,
                self.member,
                WorkspaceRole.MEMBER,
            )

    def test_role_change_does_not_change_membership_status(self):
        self.change_role(
            self.owner,
            self.member,
            WorkspaceRole.ADMIN,
        )

        self.member_membership.refresh_from_db()
        self.assertEqual(
            self.member_membership.status,
            MembershipStatus.ACTIVE,
        )

    def test_role_change_does_not_change_organization_membership(self):
        self.change_role(
            self.owner,
            self.member,
            WorkspaceRole.ADMIN,
        )

        org_membership = OrganizationMembership.objects.get(
            organization=self.organization,
            user=self.member,
        )

        self.assertEqual(
            org_membership.status,
            OrganizationMembershipStatus.ACTIVE,
        )
        self.assertEqual(
            org_membership.role,
            OrganizationRole.MEMBER,
        )


class DeleteWorkspaceTests(TestCase):
    def setUp(self):
        self.User = get_user_model()

        self.owner = self.User.objects.create_user(
            email="owner-delete@example.com",
            password="testpass123",
        )
        self.admin = self.User.objects.create_user(
            email="admin-delete@example.com",
            password="testpass123",
        )
        self.member = self.User.objects.create_user(
            email="member-delete@example.com",
            password="testpass123",
        )
        self.outsider = self.User.objects.create_user(
            email="outsider-delete@example.com",
            password="testpass123",
        )

        self.organization = Organization.objects.create(
            name="Delete Test Organization",
            created_by=self.owner,
        )

        for user, role in [
            (self.owner, OrganizationRole.OWNER),
            (self.admin, OrganizationRole.ADMIN),
            (self.member, OrganizationRole.MEMBER),
        ]:
            OrganizationMembership.objects.create(
                organization=self.organization,
                user=user,
                role=role,
                status=OrganizationMembershipStatus.ACTIVE,
            )

        self.workspace = Workspace.objects.create(
            organization=self.organization,
            name="Delete Test Workspace",
            created_by=self.owner,
        )

        self.owner_membership = self.create_membership(
            self.owner,
            WorkspaceRole.OWNER,
        )
        self.admin_membership = self.create_membership(
            self.admin,
            WorkspaceRole.ADMIN,
        )
        self.member_membership = self.create_membership(
            self.member,
            WorkspaceRole.MEMBER,
        )

    def create_membership(self, user, role):
        return WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=user,
            role=role,
            status=MembershipStatus.ACTIVE,
        )

    def delete(self, actor):
        return delete_workspace(
            workspace=self.workspace,
            actor=actor,
        )

    def test_owner_can_delete_workspace(self):
        workspace = self.delete(self.owner)

        self.assertIsNotNone(workspace.deleted_at)

    def test_deleted_workspace_is_not_in_active_manager(self):
        self.delete(self.owner)

        self.assertFalse(
            Workspace.objects.filter(pk=self.workspace.pk).exists()
        )

    def test_deleted_workspace_remains_in_all_objects(self):
        self.delete(self.owner)

        self.assertTrue(
            Workspace.all_objects.filter(pk=self.workspace.pk).exists()
        )

    def test_admin_cannot_delete_workspace(self):
        with self.assertRaises(ValidationError):
            self.delete(self.admin)

    def test_member_cannot_delete_workspace(self):
        with self.assertRaises(ValidationError):
            self.delete(self.member)

    def test_non_member_cannot_delete_workspace(self):
        with self.assertRaises(ValidationError):
            self.delete(self.outsider)

    def test_suspended_owner_cannot_delete_workspace(self):
        self.owner_membership.status = MembershipStatus.SUSPENDED
        self.owner_membership.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            self.delete(self.owner)

    def test_left_owner_cannot_delete_workspace(self):
        self.owner_membership.status = MembershipStatus.LEFT
        self.owner_membership.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            self.delete(self.owner)

    def test_already_deleted_workspace_cannot_be_deleted_again(self):
        self.delete(self.owner)

        with self.assertRaises(ValidationError):
            self.delete(self.owner)

    def test_deletion_does_not_delete_memberships(self):
        self.delete(self.owner)

        self.assertEqual(
            WorkspaceMembership.objects.filter(
                workspace=self.workspace
            ).count(),
            3,
        )

    def test_deletion_does_not_change_membership_statuses(self):
        self.delete(self.owner)

        self.member_membership.refresh_from_db()
        self.admin_membership.refresh_from_db()

        self.assertEqual(
            self.member_membership.status,
            MembershipStatus.ACTIVE,
        )
        self.assertEqual(
            self.admin_membership.status,
            MembershipStatus.ACTIVE,
        )

    def test_deleted_organization_prevents_workspace_deletion(self):
        self.organization.soft_delete()

        with self.assertRaises(ValidationError):
            self.delete(self.owner)


class RestoreWorkspaceTests(TestCase):
    def setUp(self):
        self.User = get_user_model()

        self.owner = self.User.objects.create_user(
            email="owner-restore@example.com",
            password="testpass123",
        )
        self.admin = self.User.objects.create_user(
            email="admin-restore@example.com",
            password="testpass123",
        )
        self.member = self.User.objects.create_user(
            email="member-restore@example.com",
            password="testpass123",
        )
        self.outsider = self.User.objects.create_user(
            email="outsider-restore@example.com",
            password="testpass123",
        )

        self.organization = Organization.objects.create(
            name="Restore Test Organization",
            created_by=self.owner,
        )

        for user, role in [
            (self.owner, OrganizationRole.OWNER),
            (self.admin, OrganizationRole.ADMIN),
            (self.member, OrganizationRole.MEMBER),
        ]:
            OrganizationMembership.objects.create(
                organization=self.organization,
                user=user,
                role=role,
                status=OrganizationMembershipStatus.ACTIVE,
            )

        self.workspace = Workspace.objects.create(
            organization=self.organization,
            name="Restore Test Workspace",
            created_by=self.owner,
        )

        self.owner_membership = self.create_membership(
            self.owner,
            WorkspaceRole.OWNER,
        )
        self.admin_membership = self.create_membership(
            self.admin,
            WorkspaceRole.ADMIN,
        )
        self.member_membership = self.create_membership(
            self.member,
            WorkspaceRole.MEMBER,
        )

        self.workspace.soft_delete()

    def create_membership(self, user, role):
        return WorkspaceMembership.objects.create(
            workspace=self.workspace,
            user=user,
            role=role,
            status=MembershipStatus.ACTIVE,
        )

    def restore(self, actor):
        return restore_workspace(
            workspace=self.workspace,
            actor=actor,
        )

    def test_owner_can_restore_workspace(self):
        workspace = self.restore(self.owner)

        self.assertIsNone(workspace.deleted_at)

    def test_restored_workspace_is_in_active_manager(self):
        self.restore(self.owner)

        self.assertTrue(
            Workspace.objects.filter(pk=self.workspace.pk).exists()
        )

    def test_admin_cannot_restore_workspace(self):
        with self.assertRaises(ValidationError):
            self.restore(self.admin)

    def test_member_cannot_restore_workspace(self):
        with self.assertRaises(ValidationError):
            self.restore(self.member)

    def test_non_member_cannot_restore_workspace(self):
        with self.assertRaises(ValidationError):
            self.restore(self.outsider)

    def test_suspended_owner_cannot_restore_workspace(self):
        self.owner_membership.status = MembershipStatus.SUSPENDED
        self.owner_membership.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            self.restore(self.owner)

    def test_left_owner_cannot_restore_workspace(self):
        self.owner_membership.status = MembershipStatus.LEFT
        self.owner_membership.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            self.restore(self.owner)

    def test_active_workspace_cannot_be_restored(self):
        self.workspace.restore()

        with self.assertRaises(ValidationError):
            self.restore(self.owner)

    def test_memberships_remain_after_restore(self):
        self.restore(self.owner)

        self.assertEqual(
            WorkspaceMembership.objects.filter(
                workspace=self.workspace
            ).count(),
            3,
        )

    def test_membership_statuses_remain_unchanged_after_restore(self):
        self.restore(self.owner)

        self.member_membership.refresh_from_db()
        self.admin_membership.refresh_from_db()

        self.assertEqual(
            self.member_membership.status,
            MembershipStatus.ACTIVE,
        )
        self.assertEqual(
            self.admin_membership.status,
            MembershipStatus.ACTIVE,
        )

    def test_deleted_organization_prevents_workspace_restore(self):
        self.organization.soft_delete()

        with self.assertRaises(ValidationError):
            self.restore(self.owner)
