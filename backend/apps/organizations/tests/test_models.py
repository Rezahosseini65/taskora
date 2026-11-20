
import uuid

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from apps.organizations.models import (
    MembershipStatus,
    Organization,
    OrganizationMembership,
    OrganizationRole,
)

User = get_user_model()


class OrganizationModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.com",
            password="test-password-123",
        )

    def create_organization(self, **kwargs):
        defaults = {
            "name": "Taskora",
            "created_by": self.user,
        }
        defaults.update(kwargs)
        return Organization.objects.create(**defaults)

    def test_create_organization(self):
        organization = self.create_organization()

        self.assertEqual(organization.name, "Taskora")
        self.assertEqual(organization.created_by, self.user)
        self.assertEqual(organization.membership_policy, "private")
        self.assertIsNotNone(organization.id)

    def test_name_is_unique_case_insensitively(self):
        self.create_organization(name="taskora")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_organization(name="Taskora")

    def test_name_is_stripped_on_save(self):
        organization = self.create_organization(name="  Taskora  ")

        self.assertEqual(organization.name, "Taskora")

    def test_slug_is_generated_when_empty(self):
        organization = self.create_organization(name="Taskora Company")

        self.assertEqual(organization.slug, "Taskora-Company".lower())

    def test_custom_slug_is_preserved(self):
        organization = self.create_organization(
            name="Taskora",
            slug="custom-taskora",
        )

        self.assertEqual(organization.slug, "custom-taskora")

    def test_duplicate_slug_is_rejected_by_database(self):
        self.create_organization(name="Taskora", slug="taskora")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_organization(
                    name="Another Company",
                    slug="taskora",
                )

    def test_objects_excludes_soft_deleted_organizations(self):
        organization = self.create_organization()
        organization.soft_delete()

        self.assertFalse(
            Organization.objects.filter(pk=organization.pk).exists()
        )
        self.assertTrue(
            Organization.all_objects.filter(pk=organization.pk).exists()
        )

    def test_soft_delete(self):
        organization = self.create_organization()

        organization.soft_delete()
        organization.refresh_from_db()

        self.assertTrue(organization.is_deleted)
        self.assertIsNotNone(organization.deleted_at)

    def test_soft_delete_is_idempotent(self):
        organization = self.create_organization()
        organization.soft_delete()
        deleted_at = organization.deleted_at

        organization.soft_delete()
        organization.refresh_from_db()

        self.assertEqual(organization.deleted_at, deleted_at)

    def test_restore(self):
        organization = self.create_organization()
        organization.soft_delete()
        organization.restore()
        organization.refresh_from_db()

        self.assertFalse(organization.is_deleted)
        self.assertIsNone(organization.deleted_at)

    def test_restore_is_idempotent(self):
        organization = self.create_organization()
        organization.restore()

        self.assertFalse(organization.is_deleted)

    def test_deleted_organization_name_remains_reserved(self):
        organization = self.create_organization(name="Taskora")
        organization.soft_delete()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_organization(name="TASKORA")

    def test_deleted_organization_slug_remains_reserved(self):
        organization = self.create_organization(
            name="Taskora",
            slug="taskora",
        )
        organization.soft_delete()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_organization(
                    name="Another Company",
                    slug="taskora",
                )


class OrganizationMembershipModelTests(TestCase):
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

    def create_membership(self, **kwargs):
        defaults = {
            "organization": self.organization,
            "user": self.member,
        }
        defaults.update(kwargs)
        return OrganizationMembership.objects.create(**defaults)

    def test_create_membership(self):
        membership = self.create_membership()

        self.assertEqual(membership.organization, self.organization)
        self.assertEqual(membership.user, self.member)
        self.assertEqual(membership.role, OrganizationRole.MEMBER)
        self.assertEqual(membership.status, MembershipStatus.ACTIVE)
        self.assertIsNotNone(membership.joined_at)

    def test_user_can_join_multiple_organizations(self):
        second_organization = Organization.objects.create(
            name="Another Company",
            created_by=self.owner,
        )

        first_membership = self.create_membership()
        second_membership = OrganizationMembership.objects.create(
            organization=second_organization,
            user=self.member,
        )

        self.assertNotEqual(first_membership.pk, second_membership.pk)

    def test_duplicate_membership_is_rejected(self):
        self.create_membership()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_membership()

    def test_only_one_active_owner_per_organization(self):
        self.create_membership(
            user=self.owner,
            role=OrganizationRole.OWNER,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_membership(
                    user=self.member,
                    role=OrganizationRole.OWNER,
                )

    def test_suspended_owner_does_not_block_another_active_owner(self):
        self.create_membership(
            user=self.owner,
            role=OrganizationRole.OWNER,
            status=MembershipStatus.SUSPENDED,
        )

        membership = self.create_membership(
            user=self.member,
            role=OrganizationRole.OWNER,
        )

        self.assertEqual(membership.role, OrganizationRole.OWNER)
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


    def test_left_membership_does_not_block_new_active_owner(self):
        self.create_membership(
            user=self.owner,
            role=OrganizationRole.OWNER,
            status=MembershipStatus.LEFT,
        )

        membership = self.create_membership(
            user=self.member,
            role=OrganizationRole.OWNER,
        )

        self.assertEqual(membership.status, MembershipStatus.ACTIVE)
        self.assertEqual(membership.role, OrganizationRole.OWNER)
