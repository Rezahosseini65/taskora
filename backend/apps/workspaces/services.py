from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.organizations.models import (
    MembershipStatus as OrganizationMembershipStatus,
    OrganizationMembership,
    OrganizationRole,
    Organization,
    MembershipPolicy,
)

from .models import (
    MembershipStatus,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)


@transaction.atomic
def create_workspace(*, organization, name, created_by, **extra_fields):
    """
    Create a workspace and assign its creator as the initial owner.

    The creator must be an active member of the parent organization.
    Workspace and owner membership are created atomically.
    """
    organization = (
        organization.__class__.objects.select_for_update()
        .filter(pk=organization.pk)
        .first()
    )

    if organization is None:
        raise ValidationError(
            "The parent organization does not exist or is deleted."
        )

    organization_membership = (
        OrganizationMembership.objects.select_for_update()
        .filter(
            organization=organization,
            user=created_by,
            status=OrganizationMembershipStatus.ACTIVE,
        )
        .first()
    )

    if organization_membership is None:
        raise ValidationError(
            "The creator must be an active member of the parent organization."
        )

    if organization_membership.role not in (
        OrganizationRole.OWNER,
        OrganizationRole.ADMIN,
    ):
        raise ValidationError(
            "Only organization owners and admins can create workspaces."
        )

    workspace = Workspace(
        organization=organization,
        name=name,
        created_by=created_by,
        **extra_fields,
    )

    workspace.full_clean()
    workspace.save()

    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=created_by,
        role=WorkspaceRole.OWNER,
        status=MembershipStatus.ACTIVE,
    )

    return workspace


@transaction.atomic
def join_workspace(*, workspace, user):
    """
    Join a public workspace as a regular member.

    The user must have an active membership in the parent organization.
    Existing LEFT memberships are reactivated instead of creating
    duplicate membership records.
    """
    workspace = (
        Workspace.objects.select_for_update()
        .filter(pk=workspace.pk)
        .first()
    )

    if workspace is None:
        raise ValidationError(
            "The workspace does not exist or is deleted."
        )

    organization = workspace.organization.__class__.objects.select_for_update().filter(
        pk=workspace.organization_id,
    ).first()

    if organization is None:
        raise ValidationError(
            "The parent organization does not exist or is deleted."
        )

    if workspace.membership_policy != MembershipPolicy.PUBLIC:
        raise ValidationError(
            "Direct membership is not allowed for this workspace."
        )

    organization_membership = OrganizationMembership.objects.select_for_update().filter(
        organization=organization,
        user=user,
        status=OrganizationMembershipStatus.ACTIVE,
    ).first()

    if organization_membership is None:
        raise ValidationError(
            "You must be an active member of the parent organization."
        )

    membership = WorkspaceMembership.objects.select_for_update().filter(
        workspace=workspace,
        user=user,
    ).first()

    if membership:
        if membership.status == MembershipStatus.ACTIVE:
            raise ValidationError(
                "You are already an active member of this workspace."
            )

        if membership.status == MembershipStatus.SUSPENDED:
            raise ValidationError(
                "Your workspace membership is suspended."
            )

        membership.status = MembershipStatus.ACTIVE
        membership.role = WorkspaceRole.MEMBER
        membership.joined_at = timezone.now()

        membership.save(
            update_fields=["status", "role", "joined_at"],
        )

        return membership

    return WorkspaceMembership.objects.create(
        workspace=workspace,
        user=user,
        role=WorkspaceRole.MEMBER,
        status=MembershipStatus.ACTIVE,
    )


@transaction.atomic
def leave_workspace(*, workspace, user):
    """
    Allow an active workspace member to leave.

    Workspace owners must transfer ownership before leaving.
    Membership records are retained with LEFT status.
    """
    workspace = (
        Workspace.objects.select_for_update()
        .filter(pk=workspace.pk)
        .first()
    )

    if workspace is None:
        raise ValidationError(
            "The workspace does not exist or is deleted."
        )

    membership = WorkspaceMembership.objects.select_for_update().filter(
        workspace=workspace,
        user=user,
    ).first()

    if membership is None:
        raise ValidationError(
            "You are not a member of this workspace."
        )

    if membership.status != MembershipStatus.ACTIVE:
        raise ValidationError(
            "Only active members can leave the workspace."
        )

    if membership.role == WorkspaceRole.OWNER:
        raise ValidationError(
            "Workspace owners must transfer ownership before leaving."
        )

    membership.status = MembershipStatus.LEFT
    membership.save(update_fields=["status"])

    return membership


@transaction.atomic
def transfer_workspace_ownership(workspace, current_owner, new_owner):
    workspace = (
        Workspace.objects
        .select_for_update()
        .filter(pk=workspace.pk)
        .first()
    )

    if workspace is None:
        raise ValidationError("Workspace does not exist or is deleted.")

    organization = (
        workspace.organization.__class__.objects
        .select_for_update()
        .filter(pk=workspace.organization_id)
        .first()
    )

    if organization is None:
        raise ValidationError("Parent organization does not exist or is deleted.")

    if current_owner.pk == new_owner.pk:
        raise ValidationError("Cannot transfer ownership to yourself.")

    current_membership = (
        WorkspaceMembership.objects
        .select_for_update()
        .filter(
            workspace=workspace,
            user=current_owner,
            role=WorkspaceRole.OWNER,
            status=MembershipStatus.ACTIVE,
        )
        .first()
    )

    if current_membership is None:
        raise ValidationError("Only the active workspace owner can transfer ownership.")

    organization_membership = (
        OrganizationMembership.objects
        .select_for_update()
        .filter(
            organization=organization,
            user=new_owner,
            status=OrganizationMembershipStatus.ACTIVE,
        )
        .first()
    )

    if organization_membership is None:
        raise ValidationError(
            "New owner must be an active member of the parent organization."
        )

    new_membership = (
        WorkspaceMembership.objects
        .select_for_update()
        .filter(
            workspace=workspace,
            user=new_owner,
            status=MembershipStatus.ACTIVE,
        )
        .first()
    )

    if new_membership is None:
        raise ValidationError(
            "New owner must be an active member of the workspace."
        )

    # ابتدا مالک قبلی را تنزل می‌دهیم تا قید unique owner نقض نشود.
    current_membership.role = WorkspaceRole.ADMIN
    current_membership.save(update_fields=["role"])

    new_membership.role = WorkspaceRole.OWNER
    new_membership.save(update_fields=["role"])

    return new_membership


@transaction.atomic
def suspend_workspace_membership(*, workspace, actor, user):
    workspace = (
        Workspace.objects.select_for_update()
        .filter(pk=workspace.pk)
        .first()
    )

    if workspace is None:
        raise ValidationError("Workspace does not exist.")

    actor_membership = WorkspaceMembership.objects.select_for_update().filter(
        workspace=workspace,
        user=actor,
        status=MembershipStatus.ACTIVE,
        role__in=(WorkspaceRole.OWNER, WorkspaceRole.ADMIN),
    ).first()

    if actor_membership is None:
        raise ValidationError(
            "Only active workspace owners and admins can suspend members."
        )

    membership = WorkspaceMembership.objects.select_for_update().filter(
        workspace=workspace,
        user=user,
    ).first()

    if membership is None:
        raise ValidationError("Workspace membership does not exist.")

    if membership.status != MembershipStatus.ACTIVE:
        raise ValidationError("Only active memberships can be suspended.")

    if membership.role == WorkspaceRole.OWNER:
        raise ValidationError(
            "Workspace ownership must be transferred before suspending the owner."
        )

    if (
        actor_membership.role == WorkspaceRole.ADMIN
        and membership.role != WorkspaceRole.MEMBER
    ):
        raise ValidationError(
            "Workspace admins can only suspend regular members."
        )

    membership.status = MembershipStatus.SUSPENDED
    membership.save(update_fields=["status"])

    return membership


@transaction.atomic
def reactivate_workspace_membership(*, workspace, actor, user):
    workspace = (
        Workspace.objects.select_for_update()
        .filter(pk=workspace.pk)
        .first()
    )

    if workspace is None:
        raise ValidationError("Workspace does not exist.")

    organization = (
        Organization.objects.select_for_update()
        .filter(pk=workspace.organization_id)
        .first()
    )

    if organization is None:
        raise ValidationError("Parent organization does not exist.")

    actor_org_membership = OrganizationMembership.objects.select_for_update().filter(
        organization=organization,
        user=actor,
        status=OrganizationMembershipStatus.ACTIVE,
    ).first()

    if actor_org_membership is None:
        raise ValidationError(
            "Actor must be an active member of the parent organization."
        )

    actor_membership = WorkspaceMembership.objects.select_for_update().filter(
        workspace=workspace,
        user=actor,
        status=MembershipStatus.ACTIVE,
        role__in=(WorkspaceRole.OWNER, WorkspaceRole.ADMIN),
    ).first()

    if actor_membership is None:
        raise ValidationError(
            "Only active workspace owners and admins can reactivate members."
        )

    membership = WorkspaceMembership.objects.select_for_update().filter(
        workspace=workspace,
        user=user,
    ).first()

    if membership is None:
        raise ValidationError("Workspace membership does not exist.")

    if membership.status != MembershipStatus.SUSPENDED:
        raise ValidationError(
            "Only suspended memberships can be reactivated."
        )

    if (
        actor_membership.role == WorkspaceRole.ADMIN
        and membership.role != WorkspaceRole.MEMBER
    ):
        raise ValidationError(
            "Workspace admins can only reactivate regular members."
        )

    user_org_membership = OrganizationMembership.objects.select_for_update().filter(
        organization=organization,
        user=user,
        status=OrganizationMembershipStatus.ACTIVE,
    ).first()

    if user_org_membership is None:
        raise ValidationError(
            "User must be an active member of the parent organization."
        )

    membership.status = MembershipStatus.ACTIVE
    membership.save(update_fields=["status"])

    return membership


@transaction.atomic
def change_workspace_member_role(*, workspace, actor, user, new_role):
    workspace = (
        Workspace.objects.select_for_update()
        .filter(pk=workspace.pk)
        .first()
    )

    if workspace is None:
        raise ValidationError("Workspace does not exist.")

    actor_membership = WorkspaceMembership.objects.select_for_update().filter(
        workspace=workspace,
        user=actor,
        status=MembershipStatus.ACTIVE,
        role=WorkspaceRole.OWNER,
    ).first()

    if actor_membership is None:
        raise ValidationError(
            "Only the active workspace owner can change member roles."
        )

    if actor.pk == user.pk:
        raise ValidationError(
            "Workspace owner cannot change their own role."
        )

    if new_role not in (WorkspaceRole.ADMIN, WorkspaceRole.MEMBER):
        raise ValidationError(
            "New role must be either ADMIN or MEMBER."
        )

    membership = WorkspaceMembership.objects.select_for_update().filter(
        workspace=workspace,
        user=user,
    ).first()

    if membership is None:
        raise ValidationError("Workspace membership does not exist.")

    if membership.status != MembershipStatus.ACTIVE:
        raise ValidationError(
            "Only active memberships can have their role changed."
        )

    if membership.role == WorkspaceRole.OWNER:
        raise ValidationError(
            "Workspace ownership must be transferred separately."
        )

    if membership.role == new_role:
        raise ValidationError(
            "Member already has the requested role."
        )

    membership.role = new_role
    membership.save(update_fields=["role"])

    return membership


@transaction.atomic
def delete_workspace(*, workspace, actor):
    workspace = (
        Workspace.all_objects.select_for_update()
        .filter(pk=workspace.pk)
        .first()
    )

    if workspace is None:
        raise ValidationError("Workspace does not exist.")

    if workspace.deleted_at is not None:
        raise ValidationError("Workspace is already deleted.")

    actor_membership = WorkspaceMembership.objects.select_for_update().filter(
        workspace=workspace,
        user=actor,
        status=MembershipStatus.ACTIVE,
        role=WorkspaceRole.OWNER,
    ).first()

    if actor_membership is None:
        raise ValidationError(
            "Only the active workspace owner can delete the workspace."
        )

    if not Organization.objects.filter(
        pk=workspace.organization_id
    ).exists():
        raise ValidationError("Parent organization does not exist or is deleted.")

    workspace.soft_delete()

    return workspace


@transaction.atomic
def restore_workspace(*, workspace, actor):
    workspace = (
        Workspace.all_objects.select_for_update()
        .filter(pk=workspace.pk)
        .first()
    )

    if workspace is None:
        raise ValidationError("Workspace does not exist.")

    if workspace.deleted_at is None:
        raise ValidationError("Workspace is not deleted.")

    actor_membership = WorkspaceMembership.objects.select_for_update().filter(
        workspace=workspace,
        user=actor,
        status=MembershipStatus.ACTIVE,
        role=WorkspaceRole.OWNER,
    ).first()

    if actor_membership is None:
        raise ValidationError(
            "Only the active workspace owner can restore the workspace."
        )

    if not Organization.objects.filter(
        pk=workspace.organization_id
    ).exists():
        raise ValidationError("Parent organization does not exist or is deleted.")

    workspace.restore()

    return workspace
