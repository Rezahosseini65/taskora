from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max

from apps.boards.models import Board
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

from .models import BoardList


def _get_active_board(board_id):
    board = (
        Board.objects.select_for_update()
        .filter(pk=board_id)
        .first()
    )

    if board is None:
        raise ValidationError(
            "Board does not exist or is deleted."
        )

    if board.is_archived:
        raise ValidationError(
            "Archived boards cannot be modified."
        )

    workspace = (
        Workspace.objects.select_for_update()
        .filter(pk=board.workspace_id)
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

    return board, workspace


def _get_board_list_membership(*, workspace, actor):
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


def _require_board_list_manager(*, workspace, actor):
    membership = _get_board_list_membership(
        workspace=workspace,
        actor=actor,
    )

    if membership.role not in (
        WorkspaceRole.OWNER,
        WorkspaceRole.ADMIN,
    ):
        raise ValidationError(
            "Only workspace owners and admins can manage board lists."
        )

    return membership


def _get_active_board_list(board_list_id):
    board_list = (
        BoardList.objects.select_for_update()
        .filter(pk=board_list_id)
        .first()
    )

    if board_list is None:
        raise ValidationError(
            "Board list does not exist or is deleted."
        )

    board, workspace = _get_active_board(
        board_list.board_id
    )

    return board_list, board, workspace


def _get_next_position(*, board):
    max_position = (
        BoardList.all_objects
        .filter(board=board)
        .aggregate(max_position=Max("position"))["max_position"]
    )

    return (max_position or 0) + 1


def _require_minimum_active_lists(*, board):
    active_count = BoardList.objects.filter(
        board=board,
        is_archived=False,
    ).count()

    if active_count <= 3:
        raise ValidationError(
            "A board must have at least 3 active lists."
        )


@transaction.atomic
def create_board_list(
    *,
    board,
    actor,
    name,
    description="",
    settings=None,
):
    board, workspace = _get_active_board(board.pk)

    _require_board_list_manager(
        workspace=workspace,
        actor=actor,
    )

    name = name.strip()

    if not name:
        raise ValidationError(
            {"name": "Board list name cannot be empty."}
        )

    if len(name) > 160:
        raise ValidationError(
            {"name": "Board list name cannot exceed 160 characters."}
        )

    position = _get_next_position(board=board)

    board_list = BoardList(
        board=board,
        name=name,
        position=position,
        description=description,
        settings={} if settings is None else settings,
    )

    board_list.full_clean()
    board_list.save()

    return board_list


@transaction.atomic
def update_board_list(
    *,
    board_list,
    actor,
    name=None,
    description=None,
    settings=None,
):
    board_list, board, workspace = _get_active_board_list(
        board_list.pk
    )

    _require_board_list_manager(
        workspace=workspace,
        actor=actor,
    )

    if board_list.is_archived:
        raise ValidationError(
            "Archived board lists cannot be modified."
        )

    if name is not None:
        board_list.name = name.strip()

    if description is not None:
        board_list.description = description

    if settings is not None:
        board_list.settings = settings

    board_list.full_clean()
    board_list.save()

    return board_list


@transaction.atomic
def reorder_board_lists(*, board, actor, ordered_list_ids):
    board, workspace = _get_active_board(board.pk)
    _require_board_list_manager(workspace=workspace, actor=actor)

    if not ordered_list_ids:
        raise ValidationError("The ordered list of board lists cannot be empty.")

    if len(ordered_list_ids) != len(set(ordered_list_ids)):
        raise ValidationError("Duplicate board list IDs are not allowed.")

    board_lists = list(
        BoardList.objects.select_for_update()
        .filter(board=board)
        .order_by("position")
    )

    current_ids = {item.pk for item in board_lists}
    requested_ids = set(ordered_list_ids)

    if current_ids != requested_ids:
        raise ValidationError(
            "The ordered list must contain all active board lists exactly once."
        )

    # Keep positions belonging to soft-deleted lists reserved.
    reserved_positions = set(
        BoardList.all_objects.filter(
            board=board,
            deleted_at__isnull=False,
        ).values_list("position", flat=True)
    )

    # Move active lists temporarily above every currently used position.
    max_position = (
        BoardList.all_objects.filter(board=board)
        .aggregate(max_position=Max("position"))["max_position"]
        or 0
    )
    position_offset = max_position + len(board_lists) + 1

    for index, board_list in enumerate(board_lists, start=1):
        board_list.position = position_offset + index

    BoardList.objects.bulk_update(board_lists, ["position"])

    board_lists_by_id = {item.pk: item for item in board_lists}
    reordered_lists = []

    # Assign the requested order while skipping reserved positions.
    next_position = 1

    for board_list_id in ordered_list_ids:
        while next_position in reserved_positions:
            next_position += 1

        board_list = board_lists_by_id[board_list_id]
        board_list.position = next_position
        reordered_lists.append(board_list)
        next_position += 1

    BoardList.objects.bulk_update(reordered_lists, ["position"])

    return reordered_lists


@transaction.atomic
def archive_board_list(*, board_list, actor):
    board_list, board, workspace = _get_active_board_list(
        board_list.pk
    )

    _require_board_list_manager(
        workspace=workspace,
        actor=actor,
    )

    if board_list.is_archived:
        raise ValidationError(
            "Board list is already archived."
        )

    _require_minimum_active_lists(board=board)

    board_list.is_archived = True
    board_list.save(
        update_fields=["is_archived", "updated_at"]
    )

    return board_list


@transaction.atomic
def unarchive_board_list(*, board_list, actor):
    board_list, board, workspace = _get_active_board_list(board_list.pk)

    _require_board_list_manager(
        workspace=workspace,
        actor=actor,
    )

    if not board_list.is_archived:
        raise ValidationError("Board list is not archived.")

    board_list.is_archived = False
    board_list.save(update_fields=["is_archived", "updated_at"])

    return board_list


@transaction.atomic
def delete_board_list(*, board_list, actor):
    board_list, board, workspace = _get_active_board_list(board_list.pk)

    _require_board_list_manager(
        workspace=workspace,
        actor=actor,
    )

    _require_minimum_active_lists(board=board)

    board_list.soft_delete()

    return board_list


@transaction.atomic
def restore_board_list(*, board_list, actor):
    board_list = (
        BoardList.all_objects
        .select_for_update()
        .filter(pk=board_list.pk, deleted_at__isnull=False)
        .first()
    )

    if board_list is None:
        raise ValidationError(
            "Board list does not exist or is not deleted."
        )

    board, workspace = _get_active_board(board_list.board_id)

    _require_board_list_manager(
        workspace=workspace,
        actor=actor,
    )

    board_list.deleted_at = None
    board_list.full_clean()
    board_list.save(
        update_fields=["deleted_at", "updated_at"]
    )

    return board_list