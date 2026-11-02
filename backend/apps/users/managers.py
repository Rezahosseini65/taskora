from django.contrib.auth.models import UserManager
from django.db import models
from django.utils import timezone


class UserQuerySet(models.QuerySet):
    """Custom QuerySet for filtering and managing soft-deleted users."""

    def alive(self):
        """Return users that have not been soft-deleted."""
        return self.filter(deleted_at__isnull=True)

    def deleted(self):
        """Return users that have been soft-deleted."""
        return self.filter(deleted_at__isnull=False)

    def soft_delete(self):
        """Soft-delete all users in this QuerySet."""
        now = timezone.now()
        return self.alive().update(
            deleted_at=now,
            updated_at=now,
        )

    def restore(self):
        """Restore all soft-deleted users in this QuerySet."""
        now = timezone.now()
        return self.deleted().update(
            deleted_at=None,
            updated_at=now,
        )


class CustomUserManager(UserManager.from_queryset(UserQuerySet)):
    """Manager for users that excludes soft-deleted accounts by default."""

    def get_queryset(self):
        return super().get_queryset().alive()

    def create_user(self, email, password=None, **extra_fields):
        """Create and save a user with the given email and password."""

        if not email:
            raise ValueError("The given email must be set.")

        email = email.strip()

        if not email:
            raise ValueError("The given email must be set.")

        email = self.normalize_email(email).lower()

        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)

        return user

    def create_superuser(self, email, password=None, **extra_fields):
        """Create and save a superuser with the given email and password."""

        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")

        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, password, **extra_fields)


class AllUsersManager(UserManager.from_queryset(UserQuerySet)):
    """Manager that includes soft-deleted users."""

    pass


__all__ = [
    "UserQuerySet",
    "CustomUserManager",
    "AllUsersManager",
]