import uuid

from django.conf import settings
from django.db import models
from django.db.models import F
from django.db.models.functions import Lower, Trim
from django.utils.text import slugify


class BoardQuerySet(models.QuerySet):
    def active(self):
        return self.filter(deleted_at__isnull=True)


class ActiveBoardManager(models.Manager):
    def get_queryset(self):
        return BoardQuerySet(self.model, using=self._db).active()


class Board(models.Model):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="boards",
    )

    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=160)

    description = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_boards",
    )

    settings = models.JSONField(default=dict, blank=True)

    is_archived = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = ActiveBoardManager()
    all_objects = BoardQuerySet.as_manager()

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(
                fields=["workspace", "is_archived"],
                name="idx_board_ws_archived",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                F("workspace"),
                Lower(Trim("name")),
                name="uq_board_workspace_name_ci",
            ),
            models.UniqueConstraint(
                fields=["workspace", "slug"],
                name="uq_board_workspace_slug",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.workspace})"

    def save(self, *args, **kwargs):
        self.name = self.name.strip()

        if not self.slug:
            self.slug = self.generate_unique_slug()

        super().save(*args, **kwargs)

    def generate_unique_slug(self):
        base_slug = slugify(self.name)[:160] or "board"
        slug = base_slug
        counter = 1

        while Board.all_objects.filter(
            workspace=self.workspace,
            slug=slug,
        ).exclude(pk=self.pk).exists():
            suffix = f"-{counter}"
            slug = f"{base_slug[:160 - len(suffix)]}{suffix}"
            counter += 1

        return slug

    def soft_delete(self):
        from django.utils import timezone

        if self.deleted_at is None:
            self.deleted_at = timezone.now()
            self.save(update_fields=["deleted_at", "updated_at"])

    def restore(self):
        if self.deleted_at is not None:
            self.deleted_at = None
            self.save(update_fields=["deleted_at", "updated_at"])
