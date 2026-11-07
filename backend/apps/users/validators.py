import re

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


def validate_strong_password(password: str) -> None:
    """
    Validate password strength using custom rules.
    """

    errors = []

    if len(password) < 12:
        errors.append(
            _("Password must be at least 12 characters long.")
        )

    if not re.search(r"[A-Z]", password):
        errors.append(
            _("Password must contain at least one uppercase letter.")
        )

    if not re.search(r"[a-z]", password):
        errors.append(
            _("Password must contain at least one lowercase letter.")
        )

    if not re.search(r"\d", password):
        errors.append(
            _("Password must contain at least one digit.")
        )

    if errors:
        raise ValidationError(errors)


__all__ = ["validate_strong_password"]
