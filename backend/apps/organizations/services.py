from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import (
    MembershipStatus,
    Organization,
    OrganizationMembership,
    OrganizationRole,
    MembershipPolicy
)


@transaction.atomic
def create_organization(*, name, created_by, **extra_fields):
    """
    Create an organization and assign its creator as the initial owner.

    Validate the organization before saving and ensure that both
    organization and owner membership are created atomically.
    """
    organization = Organization(
        name=name,
        created_by=created_by,
        **extra_fields,
    )

    organization.full_clean()
    organization.save()

    OrganizationMembership.objects.create(
        organization=organization,
        user=created_by,
        role=OrganizationRole.OWNER,
        status=MembershipStatus.ACTIVE,
    )

    return organization


@transaction.atomic
def join_organization(*, organization, user):
    """
    Join a public organization as a regular member.

    Reactivate an existing left membership instead of creating
    a duplicate membership record.
    """
    organization = Organization.objects.select_for_update().get(
        pk=organization.pk,
    )

    if organization.membership_policy != MembershipPolicy.PUBLIC:
        raise ValidationError(
            "Direct membership is not allowed for this organization."
        )

    membership = OrganizationMembership.objects.select_for_update().filter(
        organization=organization,
        user=user,
    ).first()

    if membership:
        if membership.status == MembershipStatus.ACTIVE:
            raise ValidationError("You are already an active member.")

        if membership.status == MembershipStatus.SUSPENDED:
            raise ValidationError(
                "Your membership is suspended."
            )

        membership.status = MembershipStatus.ACTIVE
        membership.role = OrganizationRole.MEMBER
        membership.joined_at = timezone.now()

        membership.save(
            update_fields=["status", "role", "joined_at"],
        )

        return membership

    return OrganizationMembership.objects.create(
        organization=organization,
        user=user,
        role=OrganizationRole.MEMBER,
        status=MembershipStatus.ACTIVE,
    )


@transaction.atomic
def leave_organization(*, organization, user):
    """
    Allow an active member to leave an organization.

    Owners must transfer ownership before leaving.
    Membership records are retained with LEFT status.
    """
    organization = Organization.objects.select_for_update().get(
        pk=organization.pk,
    )

    membership = OrganizationMembership.objects.select_for_update().filter(
        organization=organization,
        user=user,
    ).first()

    if membership is None:
        raise ValidationError(
            "You are not a member of this organization."
        )

    if membership.status != MembershipStatus.ACTIVE:
        raise ValidationError(
            "Only active members can leave the organization."
        )

    if membership.role == OrganizationRole.OWNER:
        raise ValidationError(
            "Organization owners must transfer ownership before leaving."
        )

    membership.status = MembershipStatus.LEFT
    membership.save(update_fields=["status"])

    return membership


@transaction.atomic
def transfer_organization_ownership(
    *,
    organization,
    current_owner,
    new_owner,
):
    """
    Transfer organization ownership to another active member.

    The previous owner becomes an admin.
    Both membership records are updated atomically.
    """
    organization = Organization.objects.select_for_update().get(
        pk=organization.pk,
    )

    if current_owner.pk == new_owner.pk:
        raise ValidationError(
            "The current owner cannot transfer ownership to themselves."
        )

    current_membership = OrganizationMembership.objects.select_for_update().filter(
        organization=organization,
        user=current_owner,
        role=OrganizationRole.OWNER,
        status=MembershipStatus.ACTIVE,
    ).first()

    if current_membership is None:
        raise ValidationError(
            "Only the active organization owner can transfer ownership."
        )

    new_membership = OrganizationMembership.objects.select_for_update().filter(
        organization=organization,
        user=new_owner,
        status=MembershipStatus.ACTIVE,
    ).first()

    if new_membership is None:
        raise ValidationError(
            "The new owner must be an active member of this organization."
        )

    # Demote the current owner first to satisfy the unique active owner constraint.
    current_membership.role = OrganizationRole.ADMIN
    current_membership.save(update_fields=["role"])

    new_membership.role = OrganizationRole.OWNER
    new_membership.save(update_fields=["role"])

    return new_membership


@transaction.atomic
def suspend_organization_membership(
    *,
    organization,
    actor,
    target_user,
):
    """
    Suspend an organization membership.

    Owners can suspend admins and members.
    Admins can only suspend regular members.
    Active owners cannot be suspended.
    """
    organization = Organization.objects.select_for_update().get(
        pk=organization.pk,
    )

    actor_membership = OrganizationMembership.objects.select_for_update().filter(
        organization=organization,
        user=actor,
        status=MembershipStatus.ACTIVE,
    ).first()

    if actor_membership is None:
        raise ValidationError(
            "You do not have an active membership in this organization."
        )

    if actor_membership.role not in (
        OrganizationRole.OWNER,
        OrganizationRole.ADMIN,
    ):
        raise ValidationError(
            "You do not have permission to suspend members."
        )

    target_membership = OrganizationMembership.objects.select_for_update().filter(
        organization=organization,
        user=target_user,
        status=MembershipStatus.ACTIVE,
    ).first()

    if target_membership is None:
        raise ValidationError(
            "The target user does not have an active membership."
        )

    if target_membership.role == OrganizationRole.OWNER:
        raise ValidationError(
            "The organization owner cannot be suspended."
        )

    if (
        actor_membership.role == OrganizationRole.ADMIN
        and target_membership.role != OrganizationRole.MEMBER
    ):
        raise ValidationError(
            "Admins can only suspend regular members."
        )

    target_membership.status = MembershipStatus.SUSPENDED
    target_membership.save(update_fields=["status"])

    return target_membership


@transaction.atomic
def reactivate_organization_membership(
    *,
    organization,
    actor,
    target_user,
):
    """
    Reactivate a suspended organization membership.

    Owners can reactivate admins and members.
    Admins can only reactivate regular members.
    """
    organization = Organization.objects.select_for_update().get(
        pk=organization.pk,
    )
    
    actor_membership = OrganizationMembership.objects.select_for_update().filter(
        organization=organization,
        user=actor,
        status=MembershipStatus.ACTIVE,
    ).first()

    if actor_membership is None:
        raise ValidationError(
            "You do not have an active membership in this organization."
        )

    if actor_membership.role not in (
        OrganizationRole.OWNER,
        OrganizationRole.ADMIN,
    ):
        raise ValidationError(
            "You do not have permission to reactivate members."
        )

    target_membership = OrganizationMembership.objects.select_for_update().filter(
        organization=organization,
        user=target_user,
        status=MembershipStatus.SUSPENDED,
    ).first()

    if target_membership is None:
        raise ValidationError(
            "The target user does not have a suspended membership."
        )

    if (
        actor_membership.role == OrganizationRole.ADMIN
        and target_membership.role != OrganizationRole.MEMBER
    ):
        raise ValidationError(
            "Admins can only reactivate regular members."
        )

    target_membership.status = MembershipStatus.ACTIVE
    target_membership.save(update_fields=["status"])

    return target_membership


@transaction.atomic
def change_organization_member_role(
    *,
    organization,
    actor,
    target_user,
    new_role,
):
    organization = Organization.objects.select_for_update().get(
        pk=organization.pk,
    )

    actor_membership = OrganizationMembership.objects.select_for_update().filter(
        organization=organization,
        user=actor,
        status=MembershipStatus.ACTIVE,
        role=OrganizationRole.OWNER,
    ).first()

    if not actor_membership:
        raise ValidationError(
            "Only the active organization owner can change member roles."
        )

    if new_role not in (
        OrganizationRole.ADMIN,
        OrganizationRole.MEMBER,
    ):
        raise ValidationError(
            "The new role must be ADMIN or MEMBER."
        )

    target_membership = OrganizationMembership.objects.select_for_update().filter(
        organization=organization,
        user=target_user,
        status=MembershipStatus.ACTIVE,
    ).first()

    if not target_membership:
        raise ValidationError(
            "The target user must be an active organization member."
        )

    if target_membership.role == OrganizationRole.OWNER:
        raise ValidationError(
            "The organization owner's role cannot be changed here."
        )

    if target_membership.role == new_role:
        raise ValidationError(
            "The target user already has this role."
        )

    target_membership.role = new_role
    target_membership.save(update_fields=["role"])

    return target_membership