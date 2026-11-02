import uuid

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .managers import CustomUserManager, AllUsersManager


class User(AbstractBaseUser, PermissionsMixin):

    class AccountStatus(models.TextChoices):
        PENDING_VERIFICATION = (
            "pending_verification",
            _("Pending Verification"),
        )
        ACTIVE = "active", _("Active")
        SUSPENDED = "suspended", _("Suspended")
        DEACTIVATED = "deactivated", _("Deactivated")

    id = models.UUIDField(
        _("id"),
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        help_text=_("Unique UUID identifier for the user."),
    )

    email = models.EmailField(
        _("email"),
        unique=True,
        help_text=_(
            "User's email address used for authentication and communication."
        ),
    )

    status = models.CharField(
        _("status"),
        max_length=21,
        choices=AccountStatus.choices,
        default=AccountStatus.PENDING_VERIFICATION,
        help_text=_("Current lifecycle status of the user account."),
    )

    email_verified_at = models.DateTimeField(
        _("email verified at"),
        null=True,
        blank=True,
        help_text=_(
            "Date and time when the user's email address was verified."
        ),
    )

    locale = models.CharField(
        _("locale"),
        max_length=20,
        default="en",
        help_text=_("Preferred language and locale for user-facing content."),
    )

    timezone = models.CharField(
        _("timezone"),
        max_length=64,
        default="UTC",
        help_text=_(
            "User's preferred timezone for displaying dates and times."
        ),
    )

    created_at = models.DateTimeField(
        _("created at"),
        auto_now_add=True,
        help_text=_("Date and time when the user account was created."),
    )

    updated_at = models.DateTimeField(
        _("updated at"),
        auto_now=True,
        help_text=_("Date and time when the user account was last updated."),
    )

    deleted_at = models.DateTimeField(
        _("deleted at"),
        null=True,
        blank=True,
        help_text=_("Date and time when the account was soft-deleted."),
    )

    is_staff = models.BooleanField(
        _("staff status"),
        default=False,
        help_text=_(
            "Designates whether the user can access the Django admin site."
        ),
    )

    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_(
            "Designates whether the user account is enabled for authentication."
        ),
    )

    objects = CustomUserManager()
    all_objects = AllUsersManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        default_manager_name = "objects"
        base_manager_name = "all_objects"

    def clean(self):
        super().clean()
        if self.email:
            self.email = self.email.strip().lower()

    def soft_delete(self):
        """Soft-delete this user account."""
        if self.deleted_at is not None:
            return

        now = timezone.now()
        self.deleted_at = now
        self.updated_at = now

        self.save(
            using=self._state.db,
            update_fields=["deleted_at", "updated_at"],
        )

    def restore(self):
        """Restore this user account."""
        if self.deleted_at is None:
            return

        self.deleted_at = None
        self.updated_at = timezone.now()

        self.save(
            using=self._state.db,
            update_fields=["deleted_at", "updated_at"],
        )

    def __str__(self):
        return self.email
