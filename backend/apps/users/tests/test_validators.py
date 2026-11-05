from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from apps.users.validators import validate_strong_password


class ValidateStrongPasswordTests(SimpleTestCase):

    def test_valid_password(self):
        password = "StrongPassword123"

        self.assertIsNone(validate_strong_password(password))

    def test_password_shorter_than_12_characters(self):
        password = "Abc123"

        with self.assertRaises(ValidationError) as context:
            validate_strong_password(password)

        self.assertIn(
            "at least 12 characters",
            str(context.exception).lower(),
        )

    def test_password_without_uppercase_letter(self):
        password = "strongpassword123"

        with self.assertRaises(ValidationError) as context:
            validate_strong_password(password)

        self.assertIn(
            "uppercase",
            str(context.exception).lower(),
        )

    def test_password_without_lowercase_letter(self):
        password = "STRONGPASSWORD123"

        with self.assertRaises(ValidationError) as context:
            validate_strong_password(password)

        self.assertIn(
            "lowercase",
            str(context.exception).lower(),
        )

    def test_password_without_digit(self):
        password = "StrongPassword"

        with self.assertRaises(ValidationError) as context:
            validate_strong_password(password)

        self.assertIn(
            "digit",
            str(context.exception).lower(),
        )

    def test_password_with_multiple_validation_errors(self):
        password = "123456789101112"

        with self.assertRaises(ValidationError) as context:
            validate_strong_password(password)

        self.assertGreaterEqual(
            len(context.exception.messages),
            2,
        )