import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F
from django.db.models.functions import Lower, Trim
from django.utils.translation import gettext_lazy as _

class BoardListQuerySet(models.QuerySet):
    def active(self):
        return self.filter(deleted_at__isnull=True)


class ActiveBoardListManager(models.Manager):
    def get_queryset(self):
        return BoardListQuerySet(self.model, using=self._db).active()


class BoardList(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_('id')
    )
    board = models.ForeignKey(
        "boards.Board",
        on_delete=models.CASCADE,
        related_name="lists",
        verbose_name=_('board')
    )
    name = models.CharField(
        _('name'),
        max_length=160
    )
    position = models.PositiveIntegerField(
        _('position')
    )
    description = models.TextField(
        _('description'),
        blank=True
    )
    settings = models.JSONField(
        _('settings'),
        default=dict, 
        blank=True
    )
    is_archived = models.BooleanField(
        _('is archived'),
        default=False
    )
    created_at = models.DateTimeField(
        _('created at'),
        auto_now_add=True
    )
    updated_at = models.DateTimeField(
        _('updated at'),
        auto_now=True
    )
    deleted_at = models.DateTimeField(
        _('deleted at'),
        null=True, 
        blank=True
    )

    objects = ActiveBoardListManager()
    all_objects = BoardListQuerySet.as_manager()

    class Meta:
        ordering = ["position", "created_at"]
        default_manager_name = "objects"
        base_manager_name = "all_objects"

        indexes = [
            models.Index(
                fields=["board", "is_archived", "position"],
                name="idx_bl_board_arch_pos",
            ),
        ]

        constraints = [
            models.UniqueConstraint(
                F("board"),
                Lower(Trim("name")),
                name="uq_boardlist_board_name_ci",
            ),
            models.UniqueConstraint(
                fields=["board", "position"],
                name="uq_boardlist_board_position",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.board})"

    def clean(self):
        super().clean()

        self.name = self.name.strip()

        if not self.name:
            raise ValidationError({
                "name": _("Board list name cannot be empty.")
            })

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        super().save(*args, **kwargs)

    def soft_delete(self):
        from django.utils import timezone

        if self.deleted_at is None:
            self.deleted_at = timezone.now()
            self.save(update_fields=["deleted_at", "updated_at"])

    def restore(self):
        if self.deleted_at is not None:
            self.deleted_at = None
            self.save(update_fields=["deleted_at", "updated_at"])
