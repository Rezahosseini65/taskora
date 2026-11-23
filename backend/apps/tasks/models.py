import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _


class TaskQuerySet(models.QuerySet):
    def active(self):
        return self.filter(deleted_at__isnull=True)


class ActiveTaskManager(models.Manager):
    def get_queryset(self):
        return TaskQuerySet(self.model, using=self._db).active()


class Task(models.Model):

    class Priority(models.TextChoices):
        LOW = "low", _("Low")
        MEDIUM = "medium", _("Medium")
        HIGH = "high", _("High")
        URGENT = "urgent", _("Urgent")

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("id"),
    )

    board_list = models.ForeignKey(
        "boardlists.BoardList",
        on_delete=models.CASCADE,
        related_name="tasks",
        verbose_name=_("board list"),
    )

    title = models.CharField(
        _("title"),
        max_length=255,
    )

    description = models.TextField(
        _("description"),
        blank=True,
    )

    priority = models.CharField(
        _("priority"),
        max_length=10,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )

    position = models.PositiveIntegerField(
        _("position"),
    )

    start_date = models.DateField(
        _("start date"),
        null=True,
        blank=True,
    )

    due_date = models.DateField(
        _("due date"),
        null=True,
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_tasks",
        verbose_name=_("created by"),
    )

    assignees = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="TaskAssignee",
        through_fields=("task", "user"),
        related_name="assigned_tasks",
        blank=True,
        verbose_name=_("assignees"),
    )

    created_at = models.DateTimeField(
        _("created at"),
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        _("updated at"),
        auto_now=True,
    )

    deleted_at = models.DateTimeField(
        _("deleted at"),
        null=True,
        blank=True,
    )

    objects = ActiveTaskManager()
    all_objects = TaskQuerySet.as_manager()

    class Meta:
        ordering = ["position", "created_at"]
        default_manager_name = "objects"
        base_manager_name = "all_objects"

        indexes = [
            models.Index(
                fields=["board_list", "deleted_at", "position"],
                name="idx_task_list_del_pos",
            ),
            models.Index(
                fields=["board_list", "priority"],
                name="idx_task_list_priority",
            ),
            models.Index(
                fields=["board_list", "due_date"],
                name="idx_task_list_due_date",
            ),
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["board_list", "position"],
                name="uq_task_list_position",
            ),
            models.CheckConstraint(
                condition=Q(position__gt=0),
                name="ck_task_position_positive",
            ),
            models.CheckConstraint(
                condition=(
                    Q(start_date__isnull=True)
                    | Q(due_date__isnull=True)
                    | Q(start_date__lte=F("due_date"))
                ),
                name="ck_task_dates_valid",
            ),
            models.CheckConstraint(
                condition=~Q(title="") & ~Q(title__regex=r"^\s+$"),
                name="ck_task_title_not_empty",
            ),
        ]

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()

        self.title = self.title.strip()

        if not self.title:
            raise ValidationError({
                "title": _("Task title cannot be empty.")
            })

        if (
            self.start_date
            and self.due_date
            and self.start_date > self.due_date
        ):
            raise ValidationError({
                "due_date": _(
                    "Due date cannot be earlier than start date."
                )
            })

    def save(self, *args, **kwargs):
        self.title = self.title.strip()
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


class TaskAssignee(models.Model):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("id"),
    )

    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="assignee_records",
        verbose_name=_("task"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="task_assignments",
        verbose_name=_("user"),
    )

    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="task_assignments_made",
        verbose_name=_("assigned by"),
    )

    assigned_at = models.DateTimeField(
        _("assigned at"),
        auto_now_add=True,
    )

    unassigned_at = models.DateTimeField(
        _("unassigned at"),
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-assigned_at"]

        indexes = [
            models.Index(
                fields=["task", "unassigned_at"],
                name="idx_ta_task_unassigned",
            ),
            models.Index(
                fields=["user", "unassigned_at"],
                name="idx_ta_user_unassigned",
            ),
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["task", "user"],
                condition=Q(unassigned_at__isnull=True),
                name="uq_task_assignee_active",
            ),
            models.CheckConstraint(
                condition=(
                    Q(unassigned_at__isnull=True)
                    | Q(unassigned_at__gte=F("assigned_at"))
                ),
                name="ck_task_assignee_dates",
            ),
        ]

    def __str__(self):
        return f"{self.user} assigned to {self.task}"

    @property
    def is_active(self):
        return self.unassigned_at is None