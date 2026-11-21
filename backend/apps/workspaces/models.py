import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower, Trim
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from apps.organizations.models import MembershipPolicy, Organization


class ActiveWorkspaceManager(models.Manager):
    """Return only workspaces that have not been soft-deleted."""

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class AllWorkspaceManager(models.Manager):
    """Return all workspaces, including soft-deleted ones."""


class Workspace(models.Model):
    """
    Represents a workspace belonging to exactly one organization.

    Workspaces support soft deletion, configurable membership policies,
    and independent workspace-level access control.
    """

    id = models.UUIDField(
        _("ID"),
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="workspaces",
        verbose_name=_("Organization"),
    )

    name = models.CharField(
        _("Name"),
        max_length=160,
        help_text=_("The unique name of the workspace within its organization."),
    )

    slug = models.SlugField(
        _("Slug"),
        max_length=160,
        blank=True,
        help_text=_(
            "A unique URL-friendly identifier within the organization. "
            "Generated from the workspace name when left empty."
        ),
    )

    description = models.TextField(
        _("Description"),
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_workspaces",
        verbose_name=_("Created by"),
    )

    settings = models.JSONField(
        _("Settings"),
        default=dict,
        blank=True,
    )

    membership_policy = models.CharField(
        _("Membership policy"),
        max_length=10,
        choices=MembershipPolicy.choices,
        default=MembershipPolicy.PRIVATE,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Created at"),
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Updated at"),
    )

    deleted_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Deleted at"),
    )

    objects = ActiveWorkspaceManager()
    all_objects = AllWorkspaceManager()

    class Meta:
        verbose_name = _("Workspace")
        verbose_name_plural = _("Workspaces")
        ordering = ["-created_at"]
        default_manager_name = "objects"
        base_manager_name = "all_objects"

        constraints = [
            models.UniqueConstraint(
                Lower(Trim("name")),
                "organization",
                name="uq_workspace_org_name_ci",
            ),
            models.UniqueConstraint(
                fields=["organization", "slug"],
                name="uq_workspace_org_slug",
            ),
        ]

        indexes = [
            models.Index(
                fields=["organization", "membership_policy"],
                name="idx_ws_org_policy",
            ),
            models.Index(
                fields=["organization", "created_at"],
                name="idx_ws_org_created",
            ),
        ]

    def __str__(self):
        return self.name

    def __repr__(self):
        return (
            f"<Workspace id={self.id} "
            f"organization_id={self.organization_id} "
            f"name={self.name!r} slug={self.slug!r}>"
        )

    @property
    def is_deleted(self):
        """Return whether the workspace has been soft-deleted."""
        return self.deleted_at is not None

    def generate_slug(self):
        """
        Generate a URL-friendly slug from the workspace name.

        Unicode is preserved to support non-Latin workspace names.
        """
        return slugify(self.name, allow_unicode=True)[:160].strip("-")
    def clean(self):
        """Validate workspace fields and slug uniqueness."""
        super().clean()

        if self.name:
            self.name = self.name.strip()

        if not self.name:
            raise ValidationError({
                "name": _("Workspace name cannot be empty.")
            })

        if not self.slug:
            self.slug = self.generate_slug()

        if not self.slug:
            raise ValidationError({
                "slug": _(
                    "A valid slug could not be generated from the "
                    "workspace name. Please provide a slug manually."
                )
            })

        slug_queryset = Workspace.all_objects.filter(
            organization_id=self.organization_id,
            slug=self.slug,
        )

        if self.pk:
            slug_queryset = slug_queryset.exclude(pk=self.pk)

        if slug_queryset.exists():
            raise ValidationError({
                "slug": _(
                    "A workspace with this slug already exists "
                    "in this organization."
                )
            })

    def save(self, *args, **kwargs):
        """
        Normalize the workspace name and generate a slug when missing.
        """
        self.name = self.name.strip() if self.name else ""

        generated_slug = False

        if not self.slug:
            self.slug = self.generate_slug()
            generated_slug = True

        if not self.slug:
            raise ValidationError({
                "slug": _(
                    "A valid slug could not be generated from the "
                    "workspace name. Please provide a slug manually."
                )
            })

        update_fields = kwargs.get("update_fields")

        if generated_slug and update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"slug"}

        return super().save(*args, **kwargs)

    def soft_delete(self):
        """Soft-delete the workspace without removing its data."""
        if self.is_deleted:
            return

        now = timezone.now()

        self.deleted_at = now
        self.updated_at = now

        self.save(
            update_fields=["deleted_at", "updated_at"],
        )

    def restore(self):
        """Restore a previously soft-deleted workspace."""
        if not self.is_deleted:
            return

        self.deleted_at = None
        self.updated_at = timezone.now()

        self.save(
            update_fields=["deleted_at", "updated_at"],
        )


class WorkspaceRole(models.TextChoices):
    OWNER = "owner", _("Owner")
    ADMIN = "admin", _("Admin")
    MEMBER = "member", _("Member")


class MembershipStatus(models.TextChoices):
    ACTIVE = "active", _("Active")
    SUSPENDED = "suspended", _("Suspended")
    LEFT = "left", _("Left")


class WorkspaceMembership(models.Model):
    """
    Represents a user's membership in a workspace.

    A membership record is retained when a user leaves a workspace.
    Rejoining reactivates the existing record.
    """

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name=_("Workspace"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="workspace_memberships",
        verbose_name=_("User"),
    )

    role = models.CharField(
        _("Role"),
        max_length=10,
        choices=WorkspaceRole.choices,
        default=WorkspaceRole.MEMBER,
    )

    status = models.CharField(
        _("Status"),
        max_length=10,
        choices=MembershipStatus.choices,
        default=MembershipStatus.ACTIVE,
    )

    joined_at = models.DateTimeField(
        _("Joined at"),
        default=timezone.now,
    )

    created_at = models.DateTimeField(
        _("Created at"),
        auto_now_add=True,
    )

    class Meta:
        verbose_name = _("Workspace Membership")
        verbose_name_plural = _("Workspace Memberships")
        ordering = ["-joined_at"]

        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "user"],
                name="uq_ws_membership_user",
            ),
            models.UniqueConstraint(
                fields=["workspace"],
                condition=models.Q(
                    role=WorkspaceRole.OWNER,
                    status=MembershipStatus.ACTIVE,
                ),
                name="uq_ws_active_owner",
            ),
        ]

        indexes = [
            models.Index(
                fields=["user", "status"],
                name="idx_wsmem_user_status",
            ),
            models.Index(
                fields=["workspace", "status"],
                name="idx_wsmem_ws_status",
            ),
        ]

    def __str__(self):
        return f"{self.user} - {self.workspace} ({self.role})"