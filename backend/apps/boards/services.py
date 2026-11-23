from django.core.exceptions import ValidationError
from django.db import transaction

from apps.boardlists.models import BoardList, DEFAULT_BOARD_LISTS
from apps.organizations.models import (
    MembershipStatus as OrganizationMembershipStatus,
    Organization,
    OrganizationMembership,
)
from apps.workspaces.models import (
    MembershipStatus,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)

from .models import Board


def _get_active_workspace(workspace_id):
    workspace = (
        Workspace.objects.select_for_update()
        .filter(pk=workspace_id)
        .first()
    )

    if workspace is None:
        raise ValidationError(
            "Workspace does not exist or is deleted."
        )

    organization = (
        Organization.objects.select_for_update()
        .filter(pk=workspace.organization_id)
        .first()
    )

    if organization is None:
        raise ValidationError(
            "Parent organization does not exist or is deleted."
        )

    return workspace


def _get_board_membership(*, workspace, actor):
    organization_membership = (
        OrganizationMembership.objects.select_for_update()
        .filter(
            organization_id=workspace.organization_id,
            user=actor,
            status=OrganizationMembershipStatus.ACTIVE,
        )
        .first()
    )

    if organization_membership is None:
        raise ValidationError(
            "You must be an active member of the parent organization."
        )

    membership = (
        WorkspaceMembership.objects.select_for_update()
        .filter(
            workspace=workspace,
            user=actor,
            status=MembershipStatus.ACTIVE,
        )
        .first()
    )

    if membership is None:
        raise ValidationError(
            "You must be an active member of this workspace."
        )

    return membership


def _require_board_manager(*, workspace, actor):
    membership = _get_board_membership(
        workspace=workspace,
        actor=actor,
    )

    if membership.role not in (
        WorkspaceRole.OWNER,
        WorkspaceRole.ADMIN,
    ):
        raise ValidationError(
            "Only workspace owners and admins can manage boards."
        )

    return membership


@transaction.atomic
def create_board(
    *,
    workspace,
    name,
    created_by,
    slug="",
    description="",
    settings=None,
):
    workspace = _get_active_workspace(workspace.pk)

    _require_board_manager(
        workspace=workspace,
        actor=created_by,
    )

    board = Board(
        workspace=workspace,
        name=name,
        slug=slug,
        description=description,
        settings={} if settings is None else settings,
        created_by=created_by,
    )

    if not board.slug:
        board.slug = board.generate_unique_slug()

    board.full_clean()
    board.save()

    BoardList.objects.bulk_create(
        [
            BoardList(
                board=board,
                name=item["name"],
                position=item["position"],
            )
            for item in DEFAULT_BOARD_LISTS
        ]
    )

    return board


@transaction.atomic
def update_board(
    *,
    board,
    actor,
    name=None,
    slug=None,
    description=None,
    settings=None,
):
    board = (
        Board.objects.select_for_update()
        .filter(pk=board.pk)
        .first()
    )

    if board is None:
        raise ValidationError(
            "Board does not exist or is deleted."
        )

    workspace = _get_active_workspace(board.workspace_id)

    _require_board_manager(
        workspace=workspace,
        actor=actor,
    )

    if board.is_archived:
        raise ValidationError(
            "Archived boards cannot be modified."
        )

    if name is not None:
        board.name = name

    if slug is not None:
        board.slug = slug

    if description is not None:
        board.description = description

    if settings is not None:
        board.settings = settings

    board.full_clean()
    board.save()

    return board


@transaction.atomic
def archive_board(*, board, actor):
    board = (
        Board.objects.select_for_update()
        .filter(pk=board.pk)
        .first()
    )

    if board is None:
        raise ValidationError(
            "Board does not exist or is deleted."
        )

    workspace = _get_active_workspace(board.workspace_id)

    _require_board_manager(
        workspace=workspace,
        actor=actor,
    )

    if board.is_archived:
        raise ValidationError("Board is already archived.")

    board.is_archived = True
    board.save(update_fields=["is_archived", "updated_at"])

    return board


@transaction.atomic
def unarchive_board(*, board, actor):
    board = (
        Board.objects.select_for_update()
        .filter(pk=board.pk)
        .first()
    )

    if board is None:
        raise ValidationError(
            "Board does not exist or is deleted."
        )

    workspace = _get_active_workspace(board.workspace_id)

    _require_board_manager(
        workspace=workspace,
        actor=actor,
    )

    if not board.is_archived:
        raise ValidationError("Board is not archived.")

    board.is_archived = False
    board.save(update_fields=["is_archived", "updated_at"])

    return board


@transaction.atomic
def delete_board(*, board, actor):
    board = (
        Board.all_objects.select_for_update()
        .filter(pk=board.pk)
        .first()
    )

    if board is None:
        raise ValidationError("Board does not exist.")

    if board.deleted_at is not None:
        raise ValidationError("Board is already deleted.")

    workspace = _get_active_workspace(board.workspace_id)

    _require_board_manager(
        workspace=workspace,
        actor=actor,
    )

    board.soft_delete()

    return board


@transaction.atomic
def restore_board(*, board, actor):
    board = (
        Board.all_objects.select_for_update()
        .filter(pk=board.pk)
        .first()
    )

    if board is None:
        raise ValidationError("Board does not exist.")

    if board.deleted_at is None:
        raise ValidationError("Board is not deleted.")

    workspace = _get_active_workspace(board.workspace_id)

    _require_board_manager(
        workspace=workspace,
        actor=actor,
    )

    board.restore()

    return board
