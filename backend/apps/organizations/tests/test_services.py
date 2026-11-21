from unittest.mock import patch
from datetime import timedelta

from django.utils import timezone
from django.db import IntegrityError
from django.test import TestCase, TransactionTestCase
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection

from threading import Thread, Barrier

from apps.organizations.models import (
    MembershipStatus,
    Organization,
    OrganizationMembership,
    OrganizationRole,
    MembershipPolicy,
)
from apps.organizations.services import (
    create_organization, 
    join_organization,
    leave_organization,
    transfer_organization_ownership,
    suspend_organization_membership,
    reactivate_organization_membership,
    change_organization_member_role
)
from apps.users.models import User


class CreateOrganizationServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.com",
            password="test-password-123",
        )

    def test_create_organization_successfully(self):
        organization = create_organization(
            name="Taskora",
            created_by=self.user,
        )

        self.assertEqual(organization.name, "Taskora")
        self.assertEqual(organization.created_by, self.user)

        membership = OrganizationMembership.objects.get(
            organization=organization,
            user=self.user,
        )

        self.assertEqual(membership.role, OrganizationRole.OWNER)
        self.assertEqual(membership.status, MembershipStatus.ACTIVE)

    def test_create_organization_with_extra_fields(self):
        organization = create_organization(
            name="Taskora",
            created_by=self.user,
            description="Project management platform",
        )

        self.assertEqual(
            organization.description,
            "Project management platform",
        )

    def test_create_organization_rolls_back_if_membership_creation_fails(self):
        with patch(
            "apps.organizations.services.OrganizationMembership.objects.create",
            side_effect=IntegrityError("Simulated database error"),
        ):
            with self.assertRaises(IntegrityError):
                create_organization(
                    name="Taskora",
                    created_by=self.user,
                )

        self.assertFalse(
            Organization.all_objects.filter(name="Taskora").exists()
        )

    
    def test_create_organization_rejects_empty_name(self):
        with self.assertRaises(ValidationError):
            create_organization(
                name="   ",
                created_by=self.user,
            )

        self.assertEqual(Organization.all_objects.count(), 0)

    def test_create_organization_rejects_duplicate_name(self):
        create_organization(
            name="Taskora",
            created_by=self.user,
        )

        another_user = User.objects.create_user(
            email="another@example.com",
            password="test-password-123",
        )

        with self.assertRaises(ValidationError):
            create_organization(
                name=" taskora ",
                created_by=another_user,
            )

        self.assertEqual(Organization.all_objects.count(), 1)


class JoinOrganizationServiceTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com",
            password="test-password-123",
        )

        self.member = User.objects.create_user(
            email="member@example.com",
            password="test-password-123",
        )

        self.organization = create_organization(
            name="Taskora",
            created_by=self.owner,
            membership_policy=MembershipPolicy.PUBLIC,
        )

    def test_user_can_join_public_organization(self):
        membership = join_organization(
            organization=self.organization,
            user=self.member,
        )

        self.assertEqual(membership.user, self.member)
        self.assertEqual(membership.organization, self.organization)
        self.assertEqual(membership.role, OrganizationRole.MEMBER)
        self.assertEqual(membership.status, MembershipStatus.ACTIVE)

    def test_user_cannot_join_private_organization(self):
        self.organization.membership_policy = MembershipPolicy.PRIVATE
        self.organization.save(update_fields=["membership_policy"])

        with self.assertRaises(ValidationError):
            join_organization(
                organization=self.organization,
                user=self.member,
            )

        self.assertFalse(
            OrganizationMembership.objects.filter(
                organization=self.organization,
                user=self.member,
            ).exists()
        )

    def test_user_cannot_join_request_policy_organization(self):
        self.organization.membership_policy = MembershipPolicy.REQUEST
        self.organization.save(update_fields=["membership_policy"])

        with self.assertRaises(ValidationError):
            join_organization(
                organization=self.organization,
                user=self.member,
            )

    def test_user_cannot_join_twice(self):
        join_organization(
            organization=self.organization,
            user=self.member,
        )

        with self.assertRaises(ValidationError):
            join_organization(
                organization=self.organization,
                user=self.member,
            )

        self.assertEqual(
            OrganizationMembership.objects.filter(
                organization=self.organization,
                user=self.member,
            ).count(),
            1,
        )

    def test_left_member_can_rejoin(self):
        old_joined_at = timezone.now() - timedelta(days=10)

        membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.member,
            role=OrganizationRole.MEMBER,
            status=MembershipStatus.LEFT,
            joined_at=old_joined_at,
        )

        result = join_organization(
            organization=self.organization,
            user=self.member,
        )

        self.assertEqual(result.pk, membership.pk)
        self.assertEqual(result.status, MembershipStatus.ACTIVE)
        self.assertGreater(result.joined_at, old_joined_at)

        self.assertEqual(
            OrganizationMembership.objects.filter(
                organization=self.organization,
                user=self.member,
            ).count(),
            1,
        )

    def test_suspended_member_cannot_rejoin(self):
        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.member,
            role=OrganizationRole.MEMBER,
            status=MembershipStatus.SUSPENDED,
        )

        with self.assertRaises(ValidationError):
            join_organization(
                organization=self.organization,
                user=self.member,
            )

    def test_existing_owner_cannot_join_again(self):
        with self.assertRaises(ValidationError):
            join_organization(
                organization=self.organization,
                user=self.owner,
            )

        membership = OrganizationMembership.objects.get(
            organization=self.organization,
            user=self.owner,
        )

        self.assertEqual(membership.role, OrganizationRole.OWNER)
        self.assertEqual(membership.status, MembershipStatus.ACTIVE)

    def test_rejoining_member_with_admin_role_resets_role_to_member(self):
        membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.member,
            role=OrganizationRole.ADMIN,
            status=MembershipStatus.LEFT,
        )

        result = join_organization(
            organization=self.organization,
            user=self.member,
        )

        membership.refresh_from_db()

        self.assertEqual(result.pk, membership.pk)
        self.assertEqual(membership.status, MembershipStatus.ACTIVE)
        self.assertEqual(membership.role, OrganizationRole.MEMBER)

class LeaveOrganizationServiceTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com",
            password="test-password-123",
        )

        self.member = User.objects.create_user(
            email="member@example.com",
            password="test-password-123",
        )

        self.organization = create_organization(
            name="Taskora",
            created_by=self.owner,
            membership_policy=MembershipPolicy.PUBLIC,
        )

        self.membership = join_organization(
            organization=self.organization,
            user=self.member,
        )

    def test_active_member_can_leave(self):
        joined_at = self.membership.joined_at

        membership = leave_organization(
            organization=self.organization,
            user=self.member,
        )

        self.assertEqual(membership.status, MembershipStatus.LEFT)
        self.assertEqual(membership.joined_at, joined_at)

    def test_owner_cannot_leave(self):
        with self.assertRaises(ValidationError):
            leave_organization(
                organization=self.organization,
                user=self.owner,
            )

    def test_non_member_cannot_leave(self):
        another_user = User.objects.create_user(
            email="another@example.com",
            password="test-password-123",
        )

        with self.assertRaises(ValidationError):
            leave_organization(
                organization=self.organization,
                user=another_user,
            )

    def test_left_member_cannot_leave_again(self):
        leave_organization(
            organization=self.organization,
            user=self.member,
        )

        with self.assertRaises(ValidationError):
            leave_organization(
                organization=self.organization,
                user=self.member,
            )

    def test_suspended_member_cannot_leave(self):
        self.membership.status = MembershipStatus.SUSPENDED
        self.membership.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            leave_organization(
                organization=self.organization,
                user=self.member,
            )


class TransferOrganizationOwnershipTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com",
            password="test-password-123",
        )

        self.new_owner = User.objects.create_user(
            email="new-owner@example.com",
            password="test-password-123",
        )

        self.organization = create_organization(
            name="Taskora",
            created_by=self.owner,
            membership_policy=MembershipPolicy.PUBLIC,
        )

        self.new_owner_membership = join_organization(
            organization=self.organization,
            user=self.new_owner,
        )

    def test_owner_can_transfer_ownership(self):
        new_owner_membership = transfer_organization_ownership(
            organization=self.organization,
            current_owner=self.owner,
            new_owner=self.new_owner,
        )

        old_owner_membership = OrganizationMembership.objects.get(
            organization=self.organization,
            user=self.owner,
        )

        self.assertEqual(
            new_owner_membership.role,
            OrganizationRole.OWNER,
        )
        self.assertEqual(
            new_owner_membership.status,
            MembershipStatus.ACTIVE,
        )
        self.assertEqual(
            old_owner_membership.role,
            OrganizationRole.ADMIN,
        )
        self.assertEqual(
            old_owner_membership.status,
            MembershipStatus.ACTIVE,
        )

        self.assertEqual(
            OrganizationMembership.objects.filter(
                organization=self.organization,
                role=OrganizationRole.OWNER,
                status=MembershipStatus.ACTIVE,
            ).count(),
            1,
        )

    def test_non_owner_cannot_transfer_ownership(self):
        another_user = User.objects.create_user(
            email="another@example.com",
            password="test-password-123",
        )

        with self.assertRaises(ValidationError):
            transfer_organization_ownership(
                organization=self.organization,
                current_owner=another_user,
                new_owner=self.new_owner,
            )

    def test_owner_cannot_transfer_ownership_to_themselves(self):
        with self.assertRaises(ValidationError):
            transfer_organization_ownership(
                organization=self.organization,
                current_owner=self.owner,
                new_owner=self.owner,
            )

    def test_new_owner_must_be_active_member(self):
        another_user = User.objects.create_user(
            email="inactive@example.com",
            password="test-password-123",
        )

        with self.assertRaises(ValidationError):
            transfer_organization_ownership(
                organization=self.organization,
                current_owner=self.owner,
                new_owner=another_user,
            )

    def test_suspended_member_cannot_become_owner(self):
        self.new_owner_membership.status = MembershipStatus.SUSPENDED
        self.new_owner_membership.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            transfer_organization_ownership(
                organization=self.organization,
                current_owner=self.owner,
                new_owner=self.new_owner,
            )

        self.assertEqual(
            OrganizationMembership.objects.get(
                organization=self.organization,
                user=self.owner,
            ).role,
            OrganizationRole.OWNER,
        )


class SuspendOrganizationMembershipTests(TestCase):
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
        self.another_admin = User.objects.create_user(
            email="another-admin@example.com",
            password="test-password-123",
        )

        self.organization = create_organization(
            name="Taskora",
            created_by=self.owner,
            membership_policy=MembershipPolicy.PUBLIC,
        )

        self.admin_membership = join_organization(
            organization=self.organization,
            user=self.admin,
        )
        self.admin_membership.role = OrganizationRole.ADMIN
        self.admin_membership.save(update_fields=["role"])

        self.member_membership = join_organization(
            organization=self.organization,
            user=self.member,
        )

        self.another_admin_membership = join_organization(
            organization=self.organization,
            user=self.another_admin,
        )
        self.another_admin_membership.role = OrganizationRole.ADMIN
        self.another_admin_membership.save(update_fields=["role"])

    def test_owner_can_suspend_member(self):
        membership = suspend_organization_membership(
            organization=self.organization,
            actor=self.owner,
            target_user=self.member,
        )

        self.assertEqual(membership.status, MembershipStatus.SUSPENDED)

    def test_owner_can_suspend_admin(self):
        membership = suspend_organization_membership(
            organization=self.organization,
            actor=self.owner,
            target_user=self.admin,
        )

        self.assertEqual(membership.status, MembershipStatus.SUSPENDED)

    def test_admin_can_suspend_member(self):
        membership = suspend_organization_membership(
            organization=self.organization,
            actor=self.admin,
            target_user=self.member,
        )

        self.assertEqual(membership.status, MembershipStatus.SUSPENDED)

    def test_admin_cannot_suspend_another_admin(self):
        with self.assertRaises(ValidationError):
            suspend_organization_membership(
                organization=self.organization,
                actor=self.admin,
                target_user=self.another_admin,
            )

        self.another_admin_membership.refresh_from_db()
        self.assertEqual(
            self.another_admin_membership.status,
            MembershipStatus.ACTIVE,
        )

    def test_member_cannot_suspend_another_member(self):
        with self.assertRaises(ValidationError):
            suspend_organization_membership(
                organization=self.organization,
                actor=self.member,
                target_user=self.another_admin,
            )

    def test_owner_cannot_suspend_themselves(self):
        with self.assertRaises(ValidationError):
            suspend_organization_membership(
                organization=self.organization,
                actor=self.owner,
                target_user=self.owner,
            )

    def test_admin_cannot_suspend_owner(self):
        with self.assertRaises(ValidationError):
            suspend_organization_membership(
                organization=self.organization,
                actor=self.admin,
                target_user=self.owner,
            )

    def test_non_member_cannot_suspend_members(self):
        outsider = User.objects.create_user(
            email="outsider@example.com",
            password="test-password-123",
        )

        with self.assertRaises(ValidationError):
            suspend_organization_membership(
                organization=self.organization,
                actor=outsider,
                target_user=self.member,
            )


class ReactivateOrganizationMembershipTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com",
            password="testpass123",
        )
        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="testpass123",
        )
        self.member = User.objects.create_user(
            email="member@example.com",
            password="testpass123",
        )
        self.another_admin = User.objects.create_user(
            email="another-admin@example.com",
            password="testpass123",
        )
        self.outsider = User.objects.create_user(
            email="outsider@example.com",
            password="testpass123",
        )

        self.organization = create_organization(
            name="Test Organization",
            created_by=self.owner,
            membership_policy=MembershipPolicy.PUBLIC,
        )

        self.admin_membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.admin,
            role=OrganizationRole.ADMIN,
            status=MembershipStatus.ACTIVE,
        )

        self.member_membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.member,
            role=OrganizationRole.MEMBER,
            status=MembershipStatus.ACTIVE,
        )

        self.another_admin_membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.another_admin,
            role=OrganizationRole.ADMIN,
            status=MembershipStatus.ACTIVE,
        )

    def suspend(self, membership):
        membership.status = MembershipStatus.SUSPENDED
        membership.save(update_fields=["status"])

    def test_owner_can_reactivate_member(self):
        self.suspend(self.member_membership)
        original_joined_at = self.member_membership.joined_at

        membership = reactivate_organization_membership(
            organization=self.organization,
            actor=self.owner,
            target_user=self.member,
        )

        self.assertEqual(membership.status, MembershipStatus.ACTIVE)
        self.assertEqual(membership.role, OrganizationRole.MEMBER)
        self.assertEqual(membership.joined_at, original_joined_at)

    def test_owner_can_reactivate_admin(self):
        self.suspend(self.admin_membership)

        membership = reactivate_organization_membership(
            organization=self.organization,
            actor=self.owner,
            target_user=self.admin,
        )

        self.assertEqual(membership.status, MembershipStatus.ACTIVE)
        self.assertEqual(membership.role, OrganizationRole.ADMIN)

    def test_admin_can_reactivate_member(self):
        self.suspend(self.member_membership)

        membership = reactivate_organization_membership(
            organization=self.organization,
            actor=self.admin,
            target_user=self.member,
        )

        self.assertEqual(membership.status, MembershipStatus.ACTIVE)

    def test_admin_cannot_reactivate_another_admin(self):
        self.suspend(self.another_admin_membership)

        with self.assertRaises(ValidationError):
            reactivate_organization_membership(
                organization=self.organization,
                actor=self.admin,
                target_user=self.another_admin,
            )

    def test_member_cannot_reactivate_membership(self):
        self.suspend(self.another_admin_membership)

        with self.assertRaises(ValidationError):
            reactivate_organization_membership(
                organization=self.organization,
                actor=self.member,
                target_user=self.another_admin,
            )

    def test_cannot_reactivate_active_membership(self):
        with self.assertRaises(ValidationError):
            reactivate_organization_membership(
                organization=self.organization,
                actor=self.owner,
                target_user=self.member,
            )

    def test_cannot_reactivate_left_membership(self):
        self.member_membership.status = MembershipStatus.LEFT
        self.member_membership.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            reactivate_organization_membership(
                organization=self.organization,
                actor=self.owner,
                target_user=self.member,
            )

    def test_non_member_cannot_reactivate_membership(self):
        self.suspend(self.member_membership)

        with self.assertRaises(ValidationError):
            reactivate_organization_membership(
                organization=self.organization,
                actor=self.outsider,
                target_user=self.member,
            )


class ChangeOrganizationMemberRoleTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com",
            password="testpass123",
        )
        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="testpass123",
        )
        self.member = User.objects.create_user(
            email="member@example.com",
            password="testpass123",
        )

        self.organization = create_organization(
            name="Role Change Test",
            created_by=self.owner,
        )

        self.admin_membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.admin,
            role=OrganizationRole.ADMIN,
            status=MembershipStatus.ACTIVE,
        )

        self.member_membership = OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.member,
            role=OrganizationRole.MEMBER,
            status=MembershipStatus.ACTIVE,
        )

    def test_owner_promotes_member_to_admin(self):
        membership = change_organization_member_role(
            organization=self.organization,
            actor=self.owner,
            target_user=self.member,
            new_role=OrganizationRole.ADMIN,
        )

        self.assertEqual(membership.role, OrganizationRole.ADMIN)

    def test_owner_demotes_admin_to_member(self):
        membership = change_organization_member_role(
            organization=self.organization,
            actor=self.owner,
            target_user=self.admin,
            new_role=OrganizationRole.MEMBER,
        )

        self.assertEqual(membership.role, OrganizationRole.MEMBER)

    def test_admin_cannot_change_member_role(self):
        with self.assertRaises(ValidationError):
            change_organization_member_role(
                organization=self.organization,
                actor=self.admin,
                target_user=self.member,
                new_role=OrganizationRole.ADMIN,
            )

    def test_member_cannot_change_member_role(self):
        with self.assertRaises(ValidationError):
            change_organization_member_role(
                organization=self.organization,
                actor=self.member,
                target_user=self.admin,
                new_role=OrganizationRole.MEMBER,
            )

    def test_cannot_assign_owner_role(self):
        with self.assertRaises(ValidationError):
            change_organization_member_role(
                organization=self.organization,
                actor=self.owner,
                target_user=self.member,
                new_role=OrganizationRole.OWNER,
            )

    def test_cannot_change_role_of_suspended_member(self):
        self.member_membership.status = MembershipStatus.SUSPENDED
        self.member_membership.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            change_organization_member_role(
                organization=self.organization,
                actor=self.owner,
                target_user=self.member,
                new_role=OrganizationRole.ADMIN,
            )

    def test_cannot_change_role_of_left_member(self):
        self.member_membership.status = MembershipStatus.LEFT
        self.member_membership.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            change_organization_member_role(
                organization=self.organization,
                actor=self.owner,
                target_user=self.member,
                new_role=OrganizationRole.ADMIN,
            )

    def test_cannot_assign_same_role(self):
        with self.assertRaises(ValidationError):
            change_organization_member_role(
                organization=self.organization,
                actor=self.owner,
                target_user=self.member,
                new_role=OrganizationRole.MEMBER,
            )


class JoinOrganizationConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com",
            password="test-password-123",
        )
        self.member = User.objects.create_user(
            email="member@example.com",
            password="test-password-123",
        )

        self.organization = create_organization(
            name="Concurrency Test",
            created_by=self.owner,
            membership_policy=MembershipPolicy.PUBLIC,
        )

    def test_concurrent_join_creates_only_one_membership(self):
        if connection.vendor != "postgresql":
            self.skipTest("This test requires PostgreSQL.")

        barrier = Barrier(2)
        results = []

        def join():
            close_old_connections()

            try:
                barrier.wait(timeout=10)

                organization = Organization.objects.get(
                    pk=self.organization.pk,
                )
                user = User.objects.get(pk=self.member.pk)

                try:
                    join_organization(
                        organization=organization,
                        user=user,
                    )
                    results.append("joined")
                except ValidationError:
                    results.append("rejected")

            except Exception as error:
                results.append(error)

            finally:
                close_old_connections()

        threads = [
            Thread(target=join),
            Thread(target=join),
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join(timeout=15)

        self.assertFalse(
            any(thread.is_alive() for thread in threads),
            "Concurrent join threads did not finish.",
        )

        self.assertEqual(results.count("joined"), 1)
        self.assertEqual(results.count("rejected"), 1)

        self.assertEqual(
            OrganizationMembership.objects.filter(
                organization=self.organization,
                user=self.member,
            ).count(),
            1,
        )
    
    def test_concurrent_rejoin_creates_only_one_active_membership(self):
        if connection.vendor != "postgresql":
            self.skipTest("This test requires PostgreSQL.")

        OrganizationMembership.objects.create(
            organization=self.organization,
            user=self.member,
            role=OrganizationRole.MEMBER,
            status=MembershipStatus.LEFT,
        )

        barrier = Barrier(2)
        results = []

        def rejoin():
            close_old_connections()

            try:
                barrier.wait(timeout=10)

                organization = Organization.objects.get(
                    pk=self.organization.pk,
                )
                user = User.objects.get(pk=self.member.pk)

                try:
                    join_organization(
                        organization=organization,
                        user=user,
                    )
                    results.append("joined")
                except ValidationError:
                    results.append("rejected")

            except Exception as error:
                results.append(error)

            finally:
                close_old_connections()

        threads = [
            Thread(target=rejoin),
            Thread(target=rejoin),
        ]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join(timeout=15)

        self.assertFalse(
            any(thread.is_alive() for thread in threads),
            "Concurrent rejoin threads did not finish.",
        )

        self.assertEqual(results.count("joined"), 1)
        self.assertEqual(results.count("rejected"), 1)

        membership = OrganizationMembership.objects.get(
            organization=self.organization,
            user=self.member,
        )

        self.assertEqual(membership.status, MembershipStatus.ACTIVE)
        self.assertEqual(membership.role, OrganizationRole.MEMBER)
        self.assertEqual(
            OrganizationMembership.objects.filter(
                organization=self.organization,
                user=self.member,
            ).count(),
            1,
        )