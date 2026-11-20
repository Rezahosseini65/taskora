import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower, Trim
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _


class MembershipPolicy(models.TextChoices):
    PRIVATE = "private", _("Private")
    REQUEST = "request", _("Request")
    PUBLIC = "public", _("Public")


class ActiveOrganizationManager(models.Manager):
    """Return only organizations that have not been soft-deleted."""

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class AllOrganizationManager(models.Manager):
    """Return all organizations, including soft-deleted ones."""


class Organization(models.Model):
    """
    Represents an organization in Taskora.

    Organizations support soft deletion, configurable membership policies,
    and ownership tracking through the created_by relationship.
    """

    id = models.UUIDField(
        _("ID"),
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    name = models.CharField(
        _("Name"),
        max_length=160,
        help_text=_("The unique name of the organization."),
    )

    slug = models.SlugField(
        _("Slug"),
        max_length=160,
        unique=True,
        blank=True,
        help_text=_(
            "A unique URL-friendly identifier. Generated from the "
            "organization name when left empty."
        ),
    )

    description = models.TextField(
        _("Description"),
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_organizations",
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

    objects = ActiveOrganizationManager()
    all_objects = AllOrganizationManager()

    class Meta:
        verbose_name = _("Organization")
        verbose_name_plural = _("Organizations")
        ordering = ["-created_at"]
        default_manager_name = "objects"
        base_manager_name = "all_objects"

        constraints = [
            models.UniqueConstraint(
                Lower(Trim("name")),
                name="uq_organization_name_ci",
            ),
        ]

        indexes = [
            models.Index(
                fields=["membership_policy"],
                name="idx_org_policy",
            ),
            models.Index(
                fields=["created_at"],
                name="idx_org_created_at",
            ),
        ]

    def __str__(self):
        return self.name

    def __repr__(self):
        return (
            f"<Organization id={self.id} "
            f"name={self.name!r} slug={self.slug!r}>"
        )

    @property
    def is_deleted(self):
        """Return whether the organization has been soft-deleted."""
        return self.deleted_at is not None

    def generate_slug(self):
        """
        Generate a URL-friendly slug from the organization name.

        Unicode is preserved to support non-Latin organization names.
        """
        return slugify(self.name, allow_unicode=True)[:160].strip("-")

    def clean(self):
        """Validate organization fields and slug uniqueness."""
        super().clean()

        if self.name:
            self.name = self.name.strip()

        if not self.name:
            raise ValidationError({
                "name": _("Organization name cannot be empty.")
            })

        if not self.slug:
            self.slug = self.generate_slug()

        if not self.slug:
            raise ValidationError({
                "slug": _(
                    "A valid slug could not be generated from the "
                    "organization name. Please provide a slug manually."
                )
            })

        slug_queryset = Organization.all_objects.filter(
            slug=self.slug
        )

        if self.pk:
            slug_queryset = slug_queryset.exclude(pk=self.pk)

        if slug_queryset.exists():
            raise ValidationError({
                "slug": _("An organization with this slug already exists.")
            })

    def save(self, *args, **kwargs):
        """
        Normalize the organization name and generate a valid slug
        when one is not provided.
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
                    "organization name. Please provide a slug manually."
                )
            })

        update_fields = kwargs.get("update_fields")

        if generated_slug and update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"slug"}

        return super().save(*args, **kwargs)

    def soft_delete(self):
        """Soft-delete the organization without removing its data."""
        if self.is_deleted:
            return

        now = timezone.now()

        self.deleted_at = now
        self.updated_at = now

        self.save(
            update_fields=["deleted_at", "updated_at"],
        )

    def restore(self):
        """Restore a previously soft-deleted organization."""
        if not self.is_deleted:
            return

        self.deleted_at = None
        self.updated_at = timezone.now()

        self.save(
            update_fields=["deleted_at", "updated_at"],
        )


class OrganizationRole(models.TextChoices):
    OWNER = "owner", _("Owner")
    ADMIN = "admin", _("Admin")
    MEMBER = "member", _("Member")


class MembershipStatus(models.TextChoices):
    ACTIVE = "active", _("Active")
    SUSPENDED = "suspended", _("Suspended")
    LEFT = "left", _("Left")


class OrganizationMembership(models.Model):
    """
    Represents a user's membership in an organization.

    A membership record is retained when a user leaves an organization.
    Rejoining reactivates the existing record.
    """

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name=_("Organization"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="organization_memberships",
        verbose_name=_("User"),
    )

    role = models.CharField(
        _("Role"),
        max_length=10,
        choices=OrganizationRole.choices,
        default=OrganizationRole.MEMBER,
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
        verbose_name = _("Organization Membership")
        verbose_name_plural = _("Organization Memberships")
        ordering = ["-joined_at"]

        constraints = [
            models.UniqueConstraint(
                fields=["organization", "user"],
                name="uq_org_membership_user",
            ),
            models.UniqueConstraint(
                fields=["organization"],
                condition=models.Q(
                    role=OrganizationRole.OWNER,
                    status=MembershipStatus.ACTIVE,
                ),
                name="uq_org_active_owner",
            ),
        ]

        indexes = [
            models.Index(
                fields=["user", "status"],
                name="idx_orgmem_user_status",
            ),
            models.Index(
                fields=["organization", "status"],
                name="idx_orgmem_org_status",
            ),
        ]

    def __str__(self):
        return f"{self.user} - {self.organization} ({self.role})"
